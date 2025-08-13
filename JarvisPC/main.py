import os, sys, json, subprocess, yaml, time, tempfile, fnmatch, shutil
import threading, queue
from dotenv import load_dotenv
from pynput import keyboard
import speech_recognition as sr
from openai import OpenAI
from rapidfuzz import process, fuzz

# ────────────────────────────────────────────────────────────────────────
# Optional: offline TTS
# ──────────────────────────────────────────────────────────────────────
try:
    import pyttsx3
    TTS = pyttsx3.init()
except Exception:
    TTS = None
import queue, threading

TTS_QUEUE = queue.Queue()

def tts_worker():
    while True:
        text = TTS_QUEUE.get()
        if text is None:  # stop signal
            break
        try:
            if TTS:
                TTS.say(text)
                TTS.runAndWait()
        except Exception as e:
            print("[TTS error]", e)
        finally:
            TTS_QUEUE.task_done()

if TTS:
    threading.Thread(target=tts_worker, daemon=True).start()

# ──────────────────────────────────────────────────────────────────
# UI setup
# ──────────────────────────────────────────────────────────────────
import tkinter as tk
UI_EVENTS = queue.Queue(maxsize=200)

def ui_log(line: str):
    try: UI_EVENTS.put_nowait(line)
    except queue.Full: pass

class JarvisUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("JarvisPC")
        self.root.geometry("500x350")
        self.root.configure(bg="#1e1e1e")

        # header
        header = tk.Frame(self.root, bg="#1e1e1e")
        header.pack(fill="x", pady=(6, 2), padx=8)
        tk.Label(header, text="JarvisPC", fg="white", bg="#1e1e1e",
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        self.dot = tk.Canvas(header, width=12, height=12, bg="#1e1e1e", highlightthickness=0)
        self.dot.pack(side="right")
        self._set_listening(False)

        # log box
        self.text = tk.Text(self.root, bg="#111", fg="white", font=("Consolas", 10),
                            wrap="word", insertbackground="white")
        self.text.pack(fill="both", expand=True, padx=8, pady=4)
        self.text.configure(state="disabled")

        # footer
        tk.Label(self.root, text="Hold SPACE to talk • Ctrl+J for one-shot",
                 fg="#9ad1ff", bg="#1e1e1e", font=("Segoe UI", 9)).pack(pady=(0,8))

        self.root.after(60, self._drain_queue)

    def _set_listening(self, on):
        self.dot.delete("all")
        color = "#4da3ff" if on else "#444"
        self.dot.create_oval(2, 2, 10, 10, fill=color, outline=color)

    def set_listening(self, on): self.root.after(0, lambda: self._set_listening(on))

    def _drain_queue(self):
        while True:
            try: line = UI_EVENTS.get_nowait()
            except queue.Empty: break
            self.text.configure(state="normal")
            self.text.insert("end", line + "\n")
            self.text.see("end")
            self.text.configure(state="disabled")
        self.root.after(60, self._drain_queue)

    def loop(self): self.root.mainloop()

# ──────────────────────────────────────────────────────────────────
# Auth
# ──────────────────────────────────────────────────────────────────
load_dotenv(override=True)
API_KEY = os.getenv("OPENAI_API_KEY") or ""
if not API_KEY:
    print("[!] No OPENAI_API_KEY in .env")
client = OpenAI(api_key=API_KEY)

# ──────────────────────────────────────────────────────────────────
# Actions
# ──────────────────────────────────────────────────────────────────
action.get("path")
    try:
        if typ == "exec": subprocess.Popen(path if isinstance(path,str) else [path], shell=True)
        elif typ == "open":
            if sys.platform.startswith("win"): subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
        else: return say(f"Not sure how to run type '{typ}'.")
        ui_log(f"[✓] Ran: {intent_name} → {path}")
    except Exception as e: say(f"That action failed: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# Smart-open
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
APP_INDEX = []
INDEX_READY = False
USER_PROFILE = os.environ.get("USERNAME") or "User"

PROGRAM_DIRS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    rf"C:\Users\{USER_PROFILE}\AppData\Local\Programs",
]
# Common names → actual exe/labels we might see in Program Files or shortcuts
APP_ALIASES = {
    "photoshop": ["photoshop.exe", "adobe photoshop"],
    "illustrator": ["illustrator.exe", "adobe illustrator"],
    "indesign": ["indesign.exe", "adobe indesign"],
    "after effects": ["afterfx.exe", "adobe after effects"],
    "premiere": ["premierepro.exe", "adobe premiere", "adobe premiere pro"],
    "acrobat": ["acrobat.exe", "acrobat reader", "acrord32.exe", "adobe acrobat"],
    "word": ["winword.exe", "microsoft word"],
    "excel": ["excel.exe", "microsoft excel"],
    "powerpoint": ["powerpnt.exe", "microsoft powerpoint"],
    "chrome": ["chrome.exe", "google chrome"],
    "edge": ["msedge.exe", "microsoft edge"],
    "firefox": ["firefox.exe", "mozilla firefox"],
    "rhino": ["rhino.exe", "rhinoceros"],
    "revit": ["revit.exe", "autodesk revit"],
    "sketchup": ["sketchup.exe", "trimble sketchup"],
    "lumion": ["lumion.exe"],
    "twinmotion": ["twinmotion.exe"],
    "enscape": ["enscape.exe"],
}

def build_app_index():
    """Scan Start Menu + Program Files for apps"""
    global APP_INDEX, INDEX_READY
    paths = []
    # Scan Start Menu
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith((".lnk", ".exe")):
                        paths.append(os.path.join(root, f))
    # Scan Program Files
    for d in PROGRAM_DIRS:
        if os.path.isdir(d):
            for root, _, files in os.walk(d):
                for f in files:
                    if f.lower().endswith(".exe"):
                        paths.append(os.path.join(root, f))
    # Remove duplicates
    APP_INDEX = list(set(paths))
    INDEX_READY = True
    print(f"[Index] Found {len(APP_INDEX)} apps.")

def find_best_app(name):
    """Fuzzy match an app name to our index, with alias help."""
    if not INDEX_READY or not APP_INDEX:
        return None
    names = [os.path.basename(p) for p in APP_INDEX]
    q = (name or "").strip().lower()
    # try the raw query + any aliases
    candidates = [q] + APP_ALIASES.get(q, [])
    best_score = -1
    best_idx = -1
    for term in candidates:
        res = process.extractOne(term, names, scorer=fuzz.WRatio, score_cutoff=70)
        if res:
            _, score, idx = res
            if score > best_score:
                best_score = score
                best_idx = idx
    if best_idx == -1:
        return None
    return APP_INDEX[best_idx]


def open_app_by_name(name: str) -> bool:
    """Try to open app by fuzzy name from our index, or fallback to shell."""
    p = find_best_app(name)
    if p:
        try:
            if p.lower().endswith(".exe"):
                subprocess.Popen([p], shell=True)
            else:
                # .lnk/.url — let Explorer handle
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer", p])
                else:
                    subprocess.Popen([p], shell=True)
            ui_log(f"[✓] Launched via index: {p}")
            return True
        except Exception as e:
            ui_log(f"[open_app_by_name error] {e}")

    # Try PATH (rare for big GUIs, good for CLI tools)
    exe = shutil.which(name)
    if exe:
        try:
            subprocess.Popen([exe], shell=True)
            ui_log(f"[✓] Launched via PATH: {exe}")
            return True
        except Exception as e:
            ui_log(f"[open_app_by_name PATH error] {e}")

    # Last resort: shell start (sometimes opens registered apps)
    try:
        subprocess.Popen(['cmd', '/c', 'start', '', name], shell=True)
        ui_log(f"[~] Attempted shell start: {name}")
        return True
    except Exception as e:
        ui_log(f"[open_app_by_name shell error] {e}")
    return False
er().endswith(".exe"):
                subprocess.Popen([p], shell=True)
            else:
                # .lnk/.url — let Explorer handle
                if sys.platform.startswith("win"):
                    subprocess.Popen(["explorer", p])
                else:
                    subprocess.Popen([p], shell=True)
            ui_log(f"[✓] Launched via index: {p}")
            return True
        except Exception as e:
            ui_log(f"[open_app_by_name error] {e}")

    # Try PATH (rare for big GUIs, good for CLI tools)
    exe = shutil.which(name)
    if exe:
        try:
            subprocess.Popen([exe], shell=True)
            ui_log(f"[✓] Launched via PATH: {exe}")
            return True
        except Exception as e:
            ui_log(f"[open_app_by_name PATH error] {e}")

    # Last resort: shell start (sometimes opens registered apps)
    try:
        subprocess.Popen(['cmd', '/c', 'start', '', name], shell=True)
        ui_log(f"[~] Attempted shell start: {name}")
        return True
    except Exception as e:
        ui_log(f"[open_app_by_name shell error] {e}")
    return False


def _norm(s): return s.lower().strip().replace('"', '').replace("'", "")
def _patterns(target, hints):
    t=_norm(target); pats=[f"*{t}*"]
    for h in hints or []:
        h=_norm(h)
        if h and h not in t: pats.append(f"*{h}*")
    for ext in [".lnk",".url",".exe",".pdf",".docx",".xlsx",".txt"]:
        pats.append(f"*{t}*{ext}")
    seen,out=set(),[]
    for p in pats:
        if p not in seen: seen.add(p); out.append(p)
    return out
def _search(dirpath, patterns):
    hits=[]
    if not os.path.isdir(dirpath): return hits
    for root,_,files in os.walk(dirpath):
        for f in files:
            if any(fnmatch.fnmatch(f.lower(), p.lower()) for p in patterns):
                hits.append(os.path.join(root, f)); break
    return hits
def resolve_target(target,hints=None):
    t=target.strip().strip('"')
    if os.path.isabs(t) or t.startswith("~"):
        path=os.path.expanduser(t)
        if os.path.exists(path): return ("path", path)
    for d in SEARCH_DIRS:
        hits=_search(d, _patterns(target,hints))
        if hits:
            hits.sort(key=lambda x: (not x.lower().endswith((".lnk",".exe")), len(x)))
            return ("file", hits[0])
    exe=shutil.which(target)
    if exe: return ("exe", exe)
    return (None,None)
def run_open_resolved(kind, path):
    try:
        if kind in ("path","file"):
            if sys.platform.startswith("win"): subprocess.Popen(["explorer", path])
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
        elif kind=="exe": subprocess.Popen([path], shell=True)
        else: return say("Weird, I don't know how to open that.")
        ui_log(f"[✓] Opened: {path}")
    except Exception as e: say(f"Opening failed: {e}")

# ──────────────────────────────────────────────────────────────────
# NLU + Whisper
# ──────────────────────────────────────────────────────────────────
def build_system_prompt():
    intents = list(ACTIONS.keys())
    return (
        "You are Jarvis, a witty, warm desktop assistant. "
        "Be friendly and slightly humorous.\n"
        "Return ONLY JSON:\n"
        '{"mode":"action","intent":"<intent>"}\n'
        '{"mode":"action","target":"<thing>","hints":["opt"]}\n'
        '{"mode":"chat","reply":"<reply>"}\n'
        f"INTENTS = {intents}\n"
    )
SYSTEM_PROMPT = build_system_prompt()

def nlu_parse(text):
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"system","content":SYSTEM_PROMPT},
                      {"role":"user","content":text}],
            response_format={"type":"json_object"}
        )
        return json.loads(resp.choices[0].message.content)
    except: return {"mode":"chat","reply":"Sorry, I got confused."}

def transcribe_audio(audio_data):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_data.get_wav_data()); tmp_path = tmp.name
    try:
        with open(tmp_path,"rb") as f:
            tr = client.audio.transcriptions.create(model="whisper-1", file=f)
        return tr.text
    finally:
        try: os.remove(tmp_path)
        except: pass

# ──────────────────────────────────────────────────────────────────
# Input
# ──────────────────────────────────────────────────────────────────
def listen_once():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        ui.set_listening(True)
        ui_log("🎤 Listening...")
        r.adjust_for_ambient_noise(source, duration=0.3)
        audio = r.listen(source, phrase_time_limit=6)
        ui.set_listening(False)
    return audio

PTT = {"pressed":False}
LISTEN_ENABLED = {"active":False}
MODS = {"ctrl":False}
def on_press(key):
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        MODS["ctrl"]=True; return
    if key==keyboard.Key.space: PTT["pressed"]=True; return
    try:
        if MODS["ctrl"] and getattr(key,"char","").lower()=="j":
            LISTEN_ENABLED["active"]=True
            ui_log("[hotkey] Triggered — say your command")
    except: pass
def on_release(key):
    if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        MODS["ctrl"]=False
    if key==keyboard.Key.space: PTT["pressed"]=False

# ──────────────────────────────────────────────────────────────────
# Say helper
# ──────────────────────────────────────────────────────────────────
def say(text: str):
    print("Jarvis:", text)
    if TTS:
        try:
            TTS_QUEUE.put_nowait(text)
        except queue.Full:
            print("[TTS] Queue full — skipping speech")


# ──────────────────────────────────────────────────────────────────
# Worker loop
# ──────────────────────────────────────────────────────────────────
def jarvis_loop():
    ui_log("JarvisPC ready. Hold SPACE to talk, or Ctrl+J for one-shot.")
    keyboard.Listener(on_press=on_press,on_release=on_release).start()
    try: last_mtime = os.path.getmtime("actions.yaml")
    except: last_mtime = 0
    while True:
        try:
            m = os.path.getmtime("actions.yaml")
            if m!=last_mtime:
                last_mtime = m
                global ACTIONS, SYSTEM_PROMPT
                ACTIONS = load_actions()
                SYSTEM_PROMPT = build_system_prompt()
                ui_log("[i] Reloaded actions.yaml")
        except: pass

        if PTT["pressed"] or LISTEN_ENABLED["active"]:
            audio = listen_once(); LISTEN_ENABLED["active"]=False
            try:
                text = transcribe_audio(audio)
                ui_log("You (voice): " + text)
            except Exception as e:
                say(f"Transcription had a hiccup: {e}")
                time.sleep(0.4); continue
            parsed = nlu_parse(text)
            if parsed.get("mode") == "action":
                intent = parsed.get("intent")
                if intent and intent in ACTIONS:
                    run_action(intent)
                else:
                    target = parsed.get("target", ""); hints = parsed.get("hints", [])
                    if target:
                        kind, path = resolve_target(target, hints)
                        if path:
                            run_open_resolved(kind, path)
                        else:
                            # try fuzzy app open if not found via normal search
                            if open_app_by_name(target):
                                pass
                            else:
                                say(f"I couldn’t find {target}.")
                    else:
                        say("Tell me which app, file, or folder to open.")
            else:
                say(parsed.get("reply") or "Okay.")
            time.sleep(0.4)
        else: time.sleep(0.1)

# ──────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────
if __name__=="__main__":
    ui = JarvisUI()
    # build the application index in background so "open photoshop" works
    threading.Thread(target=build_app_index, daemon=True).start()
    ui_log("[i] Indexing apps in Start Menu & Program Files...")
    threading.Thread(target=jarvis_loop, daemon=True).start()
    ui.loop()
