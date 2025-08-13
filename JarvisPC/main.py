import os, sys, json, subprocess, yaml, time, tempfile, fnmatch, shutil
from dotenv import load_dotenv
from pynput import keyboard
import speech_recognition as sr
from openai import OpenAI

# ──────────────────────────────────────────────────────────────────────────────
# 0) Optional: offline voice (pyttsx3). Safe to skip if not installed.
# ──────────────────────────────────────────────────────────────────────────────
try:
    import pyttsx3
    TTS = pyttsx3.init()
    # Optional tuning:
    # TTS.setProperty("rate", 185)   # 150–200 typical
    # TTS.setProperty("volume", 1.0) # 0.0–1.0
    # To choose a specific voice, uncomment to list then pick one by name:
    # for v in TTS.getProperty("voices"): print(v.name, v.id)
    # TTS.setProperty("voice", <some_voice_id>)
except Exception:
    TTS = None

def say(text: str):
    """Print and speak a reply."""
    print("Jarvis:", text)
    if TTS:
        try:
            TTS.say(text); TTS.runAndWait()
        except Exception:
            pass

# ──────────────────────────────────────────────────────────────────────────────
# 1) Auth: force .env to override any global values
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv(override=True)
API_KEY = os.getenv("OPENAI_API_KEY") or ""
print("Loaded API key prefix:", (API_KEY[:3] if API_KEY else ""), "...", (API_KEY[-6:] if API_KEY else ""))
client = OpenAI(api_key=API_KEY)

# ──────────────────────────────────────────────────────────────────────────────
# 2) Load actions from YAML
# ──────────────────────────────────────────────────────────────────────────────
def load_actions():
    with open("actions.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("intents", {})

ACTIONS = load_actions()

# ──────────────────────────────────────────────────────────────────────────────
# 3) Action runner for mapped intents
# ──────────────────────────────────────────────────────────────────────────────
def run_action(intent_name):
    action = ACTIONS.get(intent_name)
    if not action:
        say(f"I don't have an action called {intent_name} yet.")
        return
    typ = action.get("type")
    path = action.get("path")

    try:
        if typ == "exec":
            # supports strings with args (e.g., 'explorer.exe "C:\\Path"')
            subprocess.Popen(path if isinstance(path, str) else [path], shell=True)
        elif typ == "open":
            # Explorer keeps OneDrive/Desktop folders from flashing & closing
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        else:
            say(f"Not sure how to run type '{typ}'.")
            return
        print(f"[✓] Ran: {intent_name} → {path}")
    except Exception as e:
        say(f"That action failed: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# 4) SMART‑OPEN: search Desktop/Docs/Downloads + Start Menu shortcuts
# ──────────────────────────────────────────────────────────────────────────────
USER = os.environ.get("USERNAME") or "User"
SEARCH_DIRS = [
    rf"C:\Users\{USER}\Desktop",
    rf"C:\Users\{USER}\OneDrive\Desktop",
    rf"C:\Users\{USER}\Documents",
    rf"C:\Users\{USER}\Downloads",
    rf"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
    rf"C:\Users\{USER}\AppData\Roaming\Microsoft\Windows\Start Menu\Programs",
]

def _norm(s: str) -> str:
    return s.lower().strip().replace('"', '').replace("'", "")

def _patterns(target: str, hints):
    t = _norm(target)
    pats = [f"*{t}*"]
    for h in (hints or []):
        h = _norm(h)
        if h and h not in t:
            pats.append(f"*{h}*")
    for ext in [".lnk", ".url", ".exe", ".pdf", ".docx", ".xlsx", ".txt"]:
        pats.append(f"*{t}*{ext}")
    # unique, keep order
    seen, out = set(), []
    for p in pats:
        if p not in seen:
            seen.add(p); out.append(p)
    return out

def _search(dirpath: str, patterns):
    hits = []
    if not os.path.isdir(dirpath):
        return hits
    for root, _, files in os.walk(dirpath):
        for f in files:
            name = f.lower()
            for p in patterns:
                if fnmatch.fnmatch(name, p.lower()):
                    hits.append(os.path.join(root, f))
                    break
    return hits

def resolve_target(target: str, hints=None):
    # 1) Direct absolute/tilde path
    t = target.strip().strip('"')
    if os.path.isabs(t) or t.startswith("~"):
        path = os.path.expanduser(t)
        if os.path.exists(path):
            return ("path", path)

    # 2) Search known places + Start Menu
    pats = _patterns(target, hints or [])
    best_hit = None
    for d in SEARCH_DIRS:
        hits = _search(d, pats)
        if hits:
            # Prefer app shortcuts/executables first
            hits.sort(key=lambda x: (not x.lower().endswith((".lnk", ".exe")), len(x)))
            best_hit = hits[0]
            break
    if best_hit:
        return ("file", best_hit)

    # 3) PATH executable
    exe = shutil.which(target)
    if exe:
        return ("exe", exe)

    return (None, None)

def run_open_resolved(kind: str, path: str):
    try:
        if kind in ("path", "file"):
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        elif kind == "exe":
            subprocess.Popen([path], shell=True)
        else:
            say("Weird, I don't know how to open that.")
            return
        print(f"[✓] Opened: {path}")
    except Exception as e:
        say(f"Opening failed: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# 5) System prompt (humor + chat/action schema)  ← FIXED string quoting here
# ──────────────────────────────────────────────────────────────────────────────
def build_system_prompt():
    intents = list(ACTIONS.keys())
    return (
        "You are Jarvis, a witty, warm desktop assistant. "
        "Be friendly and lightly humorous, but always helpful and concise.\n"
        "Return ONLY JSON with one of these shapes (no extra text):\n"
        '{"mode":"action","intent":"<one of INTENTS>"}\n'
        '{"mode":"action","target":"<thing to open>","hints":["opt","synonym"]}\n'
        '{"mode":"chat","reply":"<concise witty answer, <=80 words>"}\n'
        f"INTENTS = {intents}\n"
        "Rules:\n"
        "- If user asks to open/launch/run/show a local app/file/folder, use mode=action.\n"
        "- Prefer an exact intent from INTENTS if it matches; otherwise use target/hints.\n"
        "- Otherwise use mode=chat and answer with a short, helpful, slightly witty response.\n"
        "- Avoid sarcasm that could confuse; keep the joke light and optional.\n"
    )

SYSTEM_PROMPT = build_system_prompt()

# ──────────────────────────────────────────────────────────────────────────────
# 6) Parse user input -> JSON {mode: 'action'|'chat', ...}
# ──────────────────────────────────────────────────────────────────────────────
def nlu_parse(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"[NLU error] {e}")
        return {"mode":"chat","reply":"I got tongue‑tied there. Mind asking again?"}

# ──────────────────────────────────────────────────────────────────────────────
# 7) Speech → text (Whisper API)
# ──────────────────────────────────────────────────────────────────────────────
def transcribe_audio(audio_data):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_data.get_wav_data())
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            tr = client.audio.transcriptions.create(model="whisper-1", file=f)
        return tr.text
    finally:
        try: os.remove(tmp_path)
        except Exception: pass

# ──────────────────────────────────────────────────────────────────────────────
# 8) Microphone and hotkeys: Space (PTT) + Ctrl+J (one-shot)
# ──────────────────────────────────────────────────────────────────────────────
def listen_once():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("🎤 Listening...")
        r.adjust_for_ambient_noise(source, duration=0.3)
        audio = r.listen(source, phrase_time_limit=6)
    return audio

PTT = {"pressed": False}
LISTEN_ENABLED = {"active": False}
MODS = {"ctrl": False}

def on_press(key):
    # Track Ctrl
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        MODS["ctrl"] = True; return
    # Space = push-to-talk
    if key == keyboard.Key.space:
        PTT["pressed"] = True; return
    # Ctrl+J = one-shot trigger
    try:
        if MODS["ctrl"] and getattr(key, "char", "").lower() == "j":
            LISTEN_ENABLED["active"] = True
            print("[hotkey] Triggered — say your command")
    except Exception:
        pass

def on_release(key):
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        MODS["ctrl"] = False
    if key == keyboard.Key.space:
        PTT["pressed"] = False

# ──────────────────────────────────────────────────────────────────────────────
# 9) Main loop
# ──────────────────────────────────────────────────────────────────────────────
def main():
    print("JarvisPC ready. Hold SPACE to talk, or press Ctrl+J for one command. Ctrl+C to quit.")
    listener = keyboard.Listener(on_press=on_press, on_release=on_release); listener.start()

    last_mtime = os.path.getmtime("actions.yaml")
    try:
        while True:
            # Hot‑reload actions.yaml if edited
            try:
                m = os.path.getmtime("actions.yaml")
                if m != last_mtime:
                    last_mtime = m
                    global ACTIONS, SYSTEM_PROMPT
                    ACTIONS = load_actions()
                    SYSTEM_PROMPT = build_system_prompt()
                    print("[i] Reloaded actions.yaml")
            except Exception:
                pass

            should_listen = PTT["pressed"] or LISTEN_ENABLED["active"]
            if should_listen:
                audio = listen_once()
                LISTEN_ENABLED["active"] = False  # consume one‑shot
                try:
                    text = transcribe_audio(audio)
                    print("You (voice):", text)
                except Exception as e:
                    say(f"Transcription had a hiccup: {e}")
                    time.sleep(0.4); continue

                parsed = nlu_parse(text)
                mode = parsed.get("mode")

                if mode == "action":
                    intent = parsed.get("intent")
                    if intent and intent in ACTIONS:
                        run_action(intent)
                    else:
                        target = parsed.get("target", "")
                        hints  = parsed.get("hints", [])
                        if target:
                            kind, path = resolve_target(target, hints)
                            if path:
                                run_open_resolved(kind, path)
                            else:
                                say(f"I couldn’t find {target}. Give me a hint or add it to actions.yaml.")
                        else:
                            say("Tell me which app, file, or folder to open.")
                else:
                    reply = parsed.get("reply") or "Okay."
                    say(reply)

                time.sleep(0.4)
            else:
                time.sleep(0.1)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
