import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url=os.getenv("base_url") or os.getenv("PLATICA_BASE_URL"),
    api_key=os.getenv("api_key") or os.getenv("PLATICA_API_KEY"),
)

MODEL_NAME = os.getenv("PLATICA_MODEL", "grok-4.7")

# with_raw_response nos deja ver los headers HTTP además del contenido
raw = client.chat.completions.with_raw_response.create(
    model=MODEL_NAME,
    messages=[{"role": "user", "content": "Di OK"}],
    max_tokens=5,
)

print("=== Headers relevantes ===")
for k, v in raw.headers.items():
    if any(p in k.lower() for p in ("limit", "remaining", "credit", "quota", "usage", "balance", "cost")):
        print(f"{k}: {v}")

completion = raw.parse()
print("\n=== Uso de tokens ===")
print(completion.usage)