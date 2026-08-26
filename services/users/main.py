from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Users Service", version="1.0.0")


@app.get("/profile")
async def get_profile(
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_tier: str = Header(..., alias="X-User-Tier"),
    x_request_id: str = Header("", alias="X-Request-ID"),
):
    return {
        "service": "users",
        "user_id": x_user_id,
        "tier": x_user_tier,
        "request_id": x_request_id,
        "data": {"name": "Alice", "email": "alice@example.com"},
    }


@app.post("/profile")
async def update_profile(
    request: Request,
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_tier: str = Header(..., alias="X-User-Tier"),
):
    payload = await request.json()
    return JSONResponse(
        {
            "service": "users",
            "user_id": x_user_id,
            "tier": x_user_tier,
            "updated": payload,
        }
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
