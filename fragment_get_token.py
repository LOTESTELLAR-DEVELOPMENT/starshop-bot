import requests
import json
import os
from dotenv import load_dotenv

# Загрузка переменных из .env
load_dotenv()

API_KEY = os.getenv("FRAGMENT_API_KEY")
PHONE_NUMBER = os.getenv("FRAGMENT_PHONE_NUMBER")
MNEMONICS_RAW = os.getenv("FRAGMENT_MNEMONICS")

if not API_KEY or not PHONE_NUMBER or not MNEMONICS_RAW:
    print("Ошибка: Убедитесь, что в .env заданы FRAGMENT_API_KEY, FRAGMENT_PHONE_NUMBER и FRAGMENT_MNEMONICS.")
    exit(1)

# MNEMONICS: слова через пробел или запятую
if ',' in MNEMONICS_RAW:
    MNEMONICS = [w.strip() for w in MNEMONICS_RAW.split(',') if w.strip()]
else:
    MNEMONICS = [w.strip() for w in MNEMONICS_RAW.split() if w.strip()]

url = "https://api.fragment-api.com/v1/auth/authenticate/"
data = {
    "api_key": API_KEY,
    "phone_number": PHONE_NUMBER,
    "mnemonics": MNEMONICS
}
headers = {"Content-Type": "application/json"}

print("Request data:", data)
try:
    response = requests.post(url, data=json.dumps(data), headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
    if response.status_code == 200:
        token = response.json().get("token")
        print("\nYour JWT token:")
        print(token)
        # --- Запись токена в .env ---
        env_path = ".env"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            found = False
            for i, line in enumerate(lines):
                if line.startswith("FRAGMENT_JWT_TOKEN="):
                    lines[i] = f"FRAGMENT_JWT_TOKEN={token}\n"
                    found = True
                    break
            if not found:
                lines.append(f"FRAGMENT_JWT_TOKEN={token}\n")
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)
            print("\nТокен успешно записан в .env (FRAGMENT_JWT_TOKEN)")
        else:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(f"FRAGMENT_JWT_TOKEN={token}\n")
            print("\nСоздан новый .env с FRAGMENT_JWT_TOKEN")
    else:
        print("Failed to get token. Check your credentials and mnemonics.")
except Exception as e:
    print("Error:", e) 