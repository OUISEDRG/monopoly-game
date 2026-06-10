from fastapi import FastAPI

app = FastAPI(title="Online Monopoly")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
