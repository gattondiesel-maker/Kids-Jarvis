import queue
import sounddevice as sd
import json
import requests
from vosk import Model, KaldiRecognizer

# Load Vosk model
model = Model("vosk-model-small-en-us-0.15")

samplerate = 16000
q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status)
    q.put(bytes(indata))

print("Jarvis microphone active...")

recognizer = KaldiRecognizer(model, samplerate)

with sd.RawInputStream(
    samplerate=samplerate,
    blocksize=8000,
    dtype='int16',
    channels=1,
    callback=callback
):

    print("Say something like: 'spell cat'")

    while True:

        data = q.get()

        if recognizer.AcceptWaveform(data):

            result = json.loads(recognizer.Result())
            text = result.get("text", "")

            if text:

                print("You said:", text)

                # Send spoken phrase to Jarvis
                try:
                    url = "http://127.0.0.1:5000/simulate_heard/" + text.replace(" ", "_")
                    requests.get(url)
                except:
                    print("Could not send command to Jarvis")
