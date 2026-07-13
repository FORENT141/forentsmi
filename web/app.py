import os
import secrets
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from jose import jwt, JWTError

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import SECRET_KEY, ADMIN_PASSWORD, WEB_HOST, WEB_PORT
import db

app = FastAPI(title="TG News Bot Panel")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24
ENV_PATH = Path(__file__).parent.parent / ".env"


def create_token(password: str) -> str:
    if password != ADMIN_PASSWORD:
        return ""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    return jwt.encode({"exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(request: Request) -> bool:
    token = request.cookies.get("token")
    if not token:
        return False
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return True
    except JWTError:
        return False


def require_auth(request: Request):
    if not verify_token(request):
        raise HTTPException(status_code=303, headers={"Location": "/login"})


def update_env(key: str, value: str):
    env_lines = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == key:
                env_lines.append(f"{key}={value}")
                found = True
            else:
                env_lines.append(line)
    if not found:
        env_lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(env_lines) + "\n")
    os.environ[key] = value


@app.on_event("startup")
async def startup():
    await db.get_db()


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if verify_token(request):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html")


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    token = create_token(password)
    if not token:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Wrong password"}
        )
    resp = RedirectResponse("/dashboard", status_code=303)
    resp.set_cookie("token", token, httponly=True, max_age=TOKEN_EXPIRY_HOURS * 3600)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("token")
    return resp


@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    stats = await db.get_stats()
    channels = await db.get_channels()
    recent = await db.get_posts(limit=10)
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"stats": stats, "channels": channels, "recent": recent},
    )


@app.get("/channels", response_class=HTMLResponse)
async def channels_page(request: Request):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    channels = await db.get_channels()
    return templates.TemplateResponse(
        request, "channels.html", {"channels": channels}
    )


@app.post("/channels/add")
async def add_channel(request: Request, username: str = Form(...), title: str = Form("")):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    await db.add_channel(username, title)
    return RedirectResponse("/channels", status_code=303)


@app.post("/channels/toggle/{username}")
async def toggle_channel(request: Request, username: str):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    await db.toggle_channel(username)
    return RedirectResponse("/channels", status_code=303)


@app.post("/channels/remove/{username}")
async def remove_channel(request: Request, username: str):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    await db.remove_channel(username)
    return RedirectResponse("/channels", status_code=303)


@app.get("/moderation", response_class=HTMLResponse)
async def moderation_page(request: Request, page: int = 1):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    per_page = 20
    posts = await db.get_posts(status="pending", limit=per_page, offset=(page - 1) * per_page)
    return templates.TemplateResponse(
        request, "moderation.html",
        {"posts": posts, "page": page},
    )


@app.post("/moderation/approve/{post_id}")
async def approve_post(request: Request, post_id: int):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    from publisher.paraphrase import paraphrase_text
    from publisher.bot import publish_to_channel

    post = await db.get_post(post_id)
    if not post:
        raise HTTPException(404)

    target = await db.get_setting("target_channel")
    text = post["paraphrased_text"] or await paraphrase_text(post["original_text"])

    await db.update_post(post_id, paraphrased_text=text, status="publishing")
    try:
        await publish_to_channel(
            channel=target,
            text=text,
            media_path=post["media_path"],
            media_type=post["media_type"],
        )
        from datetime import datetime as dt
        await db.update_post(post_id, status="published", published_at=dt.utcnow().isoformat(), error="")
    except Exception as e:
        await db.update_post(post_id, status="error", error=str(e))

    return RedirectResponse("/moderation", status_code=303)


@app.post("/moderation/skip/{post_id}")
async def skip_post(request: Request, post_id: int):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    await db.update_post(post_id, status="skipped")
    return RedirectResponse("/moderation", status_code=303)


@app.post("/moderation/edit/{post_id}")
async def edit_post(request: Request, post_id: int, paraphrased_text: str = Form(...)):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    await db.update_post(post_id, paraphrased_text=paraphrased_text)
    return RedirectResponse("/moderation", status_code=303)


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request, status: str = "published", page: int = 1):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    per_page = 20
    posts = await db.get_posts(status=status, limit=per_page, offset=(page - 1) * per_page)
    return templates.TemplateResponse(
        request, "history.html",
        {"posts": posts, "current_status": status, "page": page},
    )


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)
    settings = {}
    for key in [
        "paraphrase_prompt", "auto_publish", "target_channel", "check_interval",
        "bot_token", "telegram_api_id", "telegram_api_hash",
        "openai_api_key", "openai_model",
    ]:
        settings[key] = await db.get_setting(key)
    return templates.TemplateResponse(
        request, "settings.html", {"settings": settings}
    )


@app.post("/settings")
async def save_settings(
    request: Request,
    paraphrase_prompt: str = Form(""),
    auto_publish: str = Form("0"),
    target_channel: str = Form(""),
    check_interval: str = Form("60"),
    bot_token: str = Form(""),
    telegram_api_id: str = Form(""),
    telegram_api_hash: str = Form(""),
    openai_api_key: str = Form(""),
    openai_model: str = Form(""),
):
    if not verify_token(request):
        return RedirectResponse("/login", status_code=303)

    await db.set_setting("paraphrase_prompt", paraphrase_prompt)
    await db.set_setting("auto_publish", "1" if auto_publish == "on" else "0")
    await db.set_setting("target_channel", target_channel.lstrip("@"))
    await db.set_setting("check_interval", check_interval)
    await db.set_setting("bot_token", bot_token)
    await db.set_setting("telegram_api_id", telegram_api_id)
    await db.set_setting("telegram_api_hash", telegram_api_hash)
    await db.set_setting("openai_api_key", openai_api_key)
    await db.set_setting("openai_model", openai_model)

    if bot_token:
        update_env("BOT_TOKEN", bot_token)
    if telegram_api_id:
        update_env("TELEGRAM_API_ID", telegram_api_id)
    if telegram_api_hash:
        update_env("TELEGRAM_API_HASH", telegram_api_hash)
    if openai_api_key:
        update_env("OPENAI_API_KEY", openai_api_key)
    if openai_model:
        update_env("OPENAI_MODEL", openai_model)

    return RedirectResponse("/settings", status_code=303)


def run_web():
    import uvicorn
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT)
