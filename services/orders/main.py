from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Orders Service", version="1.0.0")


@app.get("/orders")
async def list_orders(
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_tier: str = Header(..., alias="X-User-Tier"),
    x_request_id: str = Header("", alias="X-Request-ID"),
):
    return {
        "service": "orders",
        "user_id": x_user_id,
        "tier": x_user_tier,
        "request_id": x_request_id,
        "orders": [
            {"id": "ord_1", "total": 49.99},
            {"id": "ord_2", "total": 19.99},
        ],
    }


@app.post("/orders")
async def create_order(
    request: Request,
    x_user_id: str = Header(..., alias="X-User-Id"),
    x_user_tier: str = Header(..., alias="X-User-Tier"),
):
    payload = await request.json()
    return JSONResponse(
        {
            "service": "orders",
            "user_id": x_user_id,
            "tier": x_user_tier,
            "created": payload,
        },
        status_code=201,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
