from flask import Flask, render_template, jsonify, request, send_file
import threading
import time
import subprocess
import requests
import os

app = Flask(__name__)

current_status = "Listening..."
last_heard = ""
is_busy = False
current_process = None
last_topic = ""
last_reply = ""

conversation_memory = []
MAX_MEMORY = 6

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:3b"

REPLY_AUDIO_PATH = "/home/jarvis/jarvis/static/jarvis_reply.wav"

SYSTEM_PROMPT = """
You are Jarvis, a friendly offline family assistant.
Be concise, clear, and natural.
Keep answers short unless asked for detail.
If asked to spell a word, respond with:
SPELL:<word>
Example: SPELL:saxophone
Use recent conversation context when helpful.
"""

def stop_speaking():
    global current_process, current_status, is_busy

    if current_process is not None:
        try:
            current_process.terminate()
            current_process.wait(timeout=1)
        except Exception:
            try:
                current_process.kill()
            except Exception:
                pass

    try:
        os.system("pkill -f aplay")
    except Exception:
        pass

    current_process = None
    current_status = "Listening..."
    is_busy = False


def speak(text):
    global current_process

    safe_text = text.replace("'", "").replace('"', "")

    command = [
        "bash",
        "-c",
        f"echo '{safe_text}' | "
        f"~/piper/build/piper "
        f"--model ~/jarvis/en_US-lessac-medium.onnx "
        f"--config ~/jarvis/en_US-lessac-medium.onnx.json "
        f"--espeak_data ~/piper/build/pi/share/espeak-ng-data "
        f"--output-raw | "
        f"aplay -r 22050 -f S16_LE -t raw -"
    ]

    current_process = subprocess.Popen(command)
    current_process.wait()
    current_process = None


def speak_to_file(text, output_path):
    safe_text = text.replace("'", "").replace('"', "")

    command = [
        "bash",
        "-c",
        f"echo '{safe_text}' | "
        f"~/piper/build/piper "
        f"--model ~/jarvis/en_US-lessac-medium.onnx "
        f"--config ~/jarvis/en_US-lessac-medium.onnx.json "
        f"--espeak_data ~/piper/build/pi/share/espeak-ng-data "
        f"--output_file '{output_path}'"
    ]

    subprocess.run(command, check=False)


def spell_word(word):
    speak(f"The spelling of {word} is")
    for letter in word.upper():
        speak(letter)
        time.sleep(0.07)

def ask_llm(user_text):
    global conversation_memory

    conversation_memory.append({
        "role": "user",
        "content": user_text
    })

    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory.pop(0)

    history_text = ""

    for msg in conversation_memory:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            history_text += f"User: {content}\n"
        else:
            history_text += f"Jarvis: {content}\n"

    prompt = (
        f"{SYSTEM_PROMPT}\n"
        f"{history_text}\n"
        f"Jarvis:"
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    data = response.json()
    reply = data.get("response", "").strip()

    conversation_memory.append({
        "role": "assistant",
        "content": reply
    })

    if len(conversation_memory) > MAX_MEMORY:
        conversation_memory.pop(0)

    return reply


def run_command_cycle(command_text):
    global current_status, last_heard, is_busy, last_topic, last_reply

    cleaned = command_text.lower().strip()

    if cleaned in ["stop", "stop talking", "be quiet", "quiet"]:
        stop_speaking()
        return

    if is_busy:
        return

    is_busy = True
    last_heard = command_text
    current_status = "Thinking..."

    if "spell it" in cleaned or "how do you spell it" in cleaned:
        if last_topic:
            command_text = f"How do you spell {last_topic}?"
            cleaned = command_text.lower().strip()

    try:
        reply = ask_llm(command_text)
        last_reply = reply

        print("\nUser:", command_text, flush=True)
        print("Jarvis:", reply if reply else "Sorry, I did not get that.", "\n", flush=True)

        reply_text = reply if reply else "Sorry, I did not get that."
        speak_to_file(reply_text, REPLY_AUDIO_PATH)

        current_status = "Speaking..."

        if reply.upper().startswith("SPELL:"):
            word = reply.split(":", 1)[1].strip()
            if word:
                last_topic = word
                spell_word(word)
            else:
                speak("Please tell me the word you want help spelling.")
        else:
            if cleaned.startswith("what is "):
                possible_topic = cleaned.replace("what is ", "").strip(" ?.")
                if possible_topic:
                    last_topic = possible_topic

            speak(reply_text)

    except Exception as e:
        current_status = "Speaking..."
        error_text = "Sorry, I had trouble thinking just then."
        last_reply = error_text
        speak_to_file(error_text, REPLY_AUDIO_PATH)
        speak(error_text)
        print("LLM error:", e)

    time.sleep(0.2)
    current_status = "Listening..."
    is_busy = False

@app.route("/")
def home():
    return render_template("index.html", status=current_status)


@app.route("/status")
def status():
    return jsonify({
        "status": current_status,
        "last_heard": last_heard,
        "last_reply": last_reply,
        "is_busy": is_busy
    })


@app.route("/set_status/<new_status>")
def set_status(new_status):
    global current_status
    current_status = new_status.replace("_", " ")
    return jsonify({
        "ok": True,
        "status": current_status
    })


@app.route("/simulate_heard/<phrase>")
def simulate_heard(phrase):
    thread = threading.Thread(
        target=run_command_cycle,
        args=(phrase.replace("_", " "),)
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        "ok": True,
        "heard": phrase
    })


@app.route("/stop", methods=["GET"])
def stop_route():
    stop_speaking()
    return jsonify({"ok": True})


@app.route("/upload_audio", methods=["POST"])
def upload_audio():

    audio = request.files.get("audio")

    if not audio:
        return jsonify({"ok": False})

    webm_path = "/tmp/jarvis_remote.webm"
    wav_path = "/tmp/jarvis_remote.wav"

    audio.save(webm_path)

    # Convert webm ? wav (16k mono)
    os.system(
        f"ffmpeg -y -i {webm_path} "
        f"-ar 16000 -ac 1 -f wav {wav_path}"
    )

    try:
        from vosk import Model, KaldiRecognizer
        import wave
        import json

        model = Model("vosk-model-en-us-0.22")

        wf = wave.open(wav_path, "rb")

        recognizer = KaldiRecognizer(
            model,
            wf.getframerate()
        )

        text_result = ""

        while True:

            data = wf.readframes(4000)

            if len(data) == 0:
                break

            if recognizer.AcceptWaveform(data):

                result = json.loads(
                    recognizer.Result()
                )

                text_result += result.get(
                    "text",
                    ""
                )

        final_result = json.loads(
            recognizer.FinalResult()
        )

        text_result += final_result.get(
            "text",
            ""
        )

        text_result = text_result.strip()

        if text_result:

            run_command_cycle(text_result)

        else:

            run_command_cycle(
                "Sorry I did not hear anything"
            )

    except Exception as e:

        print("Speech error:", e)

        run_command_cycle(
            "Speech processing failed"
        )

    return jsonify({"ok": True})

@app.route("/reply_audio")
def reply_audio():
    if os.path.exists(REPLY_AUDIO_PATH):
        return send_file(REPLY_AUDIO_PATH, mimetype="audio/wav")
    return jsonify({"ok": False}), 404


@app.route("/remote")
def remote():
    return render_template("remote.html")

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        ssl_context=(
            "/home/jarvis/jarvis/cert.pem",
            "/home/jarvis/jarvis/key.pem"
        )
    )
