#!/usr/bin/env python3
"""Sirius multi-account miner.

Taruh key di accounts.txt (satu per baris), kode invite di invite.txt.
Jalan terus: python3 bot.py        Sekali jalan: python3 bot.py --once
"""
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import api


def nap(a=0.7, b=2.4):
    """Jeda antar request — selalu beda-beda, biar nggak ketahuan pola bot."""
    time.sleep(random.uniform(a, b))


def think(p=0.08, a=4.0, b=13.0):
    """Sesekali jeda panjang kayak orang lagi baca layar."""
    if random.random() < p:
        time.sleep(random.uniform(a, b))


def night():
    """01:00-06:00 WIB — orang tidur, jadi bot juga pelan."""
    wib = (datetime.now(timezone.utc) + timedelta(hours=7)).hour
    return 1 <= wib < 6

BASE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.environ.get("SIRIUS_ACCOUNTS", os.path.join(BASE, "accounts.txt"))
INVITE_FILE = os.environ.get("SIRIUS_INVITE", os.path.join(BASE, "invite.txt"))
STATE_DIR = os.path.join(BASE, "accounts")
LOG = os.path.join(BASE, "log.txt")
POLL = int(os.environ.get("SIRIUS_POLL", "600"))
MAX_RETRY = max(1, int(os.environ.get("SIRIUS_RETRY", "3")))
KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")

os.makedirs(STATE_DIR, exist_ok=True)


# ----------------------------------------------------------------- config ---
def read_inviter():
    """Kode invite dipakai buat semua akun. Isi invite.txt (satu baris)."""
    try:
        with open(INVITE_FILE) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    return line
    except OSError:
        pass
    return os.environ.get("SIRIUS_INVITER", "")


def read_accounts():
    """accounts.txt -> [(key, invite_override|None)]"""
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    out, seen = [], set()
    with open(ACCOUNTS_FILE) as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = re.split(r"[\s,;]+", line)
            key = parts[0]
            if not KEY_RE.match(key):
                print(f"lewati, bukan key 64-hex: {key[:20]}", flush=True)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append((key, parts[1] if len(parts) > 1 else None))
    return out


def state_path(key):
    return os.path.join(STATE_DIR, key[:16] + ".json")


def load_state(key):
    p = state_path(key)
    if os.path.exists(p):
        with open(p) as fh:
            return json.load(fh)
    return {"identityId": key, "installationId": str(uuid.uuid4()), "runTasks": True}


def save_state(st):
    p = state_path(st["identityId"])
    tmp = p + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(st, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def body(res):
    b = (res.get("payload") or {}).get("body")
    return b if isinstance(b, dict) else {}


def err(res):
    b = body(res)
    return b.get("errorCode") or None


def data(res):
    return body(res).get("data") or {}


# ------------------------------------------------------------------- auth ---
def do_login(st):
    r = api.call("POST", "/auth/login", {
        "identityId": st["identityId"],
        "installationId": st["installationId"],
        "platform": "android"})
    if r["status"] != 200:
        raise RuntimeError(f"login {r['status']} {err(r) or ''}".strip())
    d = data(r)
    now = int(time.time())
    st.update({
        "accessToken": d["accessToken"],
        "refreshToken": d.get("refreshToken") or st.get("refreshToken"),
        "accessTokenExpiresAt": now + int(d.get("expiresIn") or 900),
        "refreshTokenExpiresAt": now + int(d.get("refreshExpiresIn") or 0),
        "sessionId": d.get("sessionId"),
    })
    save_state(st)
    return st["accessToken"]


def ensure_token(st):
    if st.get("accessToken") and int(st.get("accessTokenExpiresAt") or 0) > time.time() + 60:
        return st["accessToken"]
    rt = st.get("refreshToken")
    if rt:
        r = api.call("POST", "/auth/refresh", {"refreshToken": rt})
        if r["status"] == 200 and data(r).get("accessToken"):
            d = data(r)
            now = int(time.time())
            st.update({
                "accessToken": d["accessToken"],
                "refreshToken": d.get("refreshToken") or rt,
                "accessTokenExpiresAt": now + int(d.get("expiresIn") or 900),
                "refreshTokenExpiresAt": now + int(d.get("refreshExpiresIn") or 0),
            })
            save_state(st)
            return st["accessToken"]
    return do_login(st)


def get(path, st, tok, _retry=True):
    r = api.call("GET", path, token=tok)
    if r["status"] == 401 and _retry:
        time.sleep(1)
        tok = ensure_token(st)
        return get(path, st, tok, _retry=False)
    return r, tok


# ------------------------------------------------------------- satu akun ----
def process(key, invite_override, inviter_default):
    st = load_state(key)
    invite = invite_override or st.get("inviterCode") or inviter_default
    out = {"code": key[:8], "note": "", "err": None}

    tok = ensure_token(st)

    # 1) profil + pasang kode invite
    r, tok = get("/users/me", st, tok)
    if r["status"] != 200:
        out["err"] = f"login {r['status']} {err(r) or ''}".strip()
        return out
    me = data(r)
    out["code"] = me.get("userCode") or key[:8]
    if not me.get("invitationBound"):
        if not invite:
            out["note"] = "invite belum diisi (isi invite.txt)"
        else:
            nap()
            rb = api.call("POST", "/users/me/inviter", {"inviterCode": invite}, token=tok)
            if rb["status"] == 200:
                out["note"] = f"invite dipasang"
            else:
                out["err"] = f"invite {rb['status']} {err(rb) or ''}".strip()
                return out
            nap()
    if invite:
        st["inviterCode"] = invite
        save_state(st)

    # 2) mining
    nap()
    r, tok = get("/mining/tasks/status", st, tok)
    ms = data(r).get("miningStatus")
    out["reward"] = data(r).get("totalMiningReward") or "0.0000"
    if ms != "RUNNING":
        time.sleep(random.uniform(3.0, 15.0))   # nggak langsung ngebut
        rs = api.call("POST", "/mining/tasks/start", {}, token=tok)
        if rs["status"] == 200:
            out["note"] = (out["note"] + " | " if out["note"] else "") + "mining dimulai"
            out["reward"] = "0.0000"
        else:
            out["err"] = f"mulai mining {rs['status']} {err(rs) or ''}".strip()
            return out
        nap()
        r, tok = get("/mining/tasks/status", st, tok)
        ms = data(r).get("miningStatus")
        out["reward"] = data(r).get("totalMiningReward") or "0.0000"
    out["mining"] = "jalan" if ms == "RUNNING" else (ms or "?").lower()

    # 3) task
    out["task"] = "-"
    if st.get("runTasks", True):
        nap()
        rl, tok = get("/tasks", st, tok)
        tasks = data(rl).get("tasks") or []
        sudah = sum(1 for t in tasks if t.get("participated"))
        baru, hadiah = 0, 0.0
        for t in tasks:
            if t.get("participated"):
                continue
            nap(1.4, 3.2)
            rp = api.call("POST", f"/tasks/{t['taskId']}/participations", {}, token=tok)
            if rp["status"] == 200:
                baru += 1
                try:
                    hadiah += float((data(rp).get("amount") or 0))
                except Exception:
                    pass
            elif rp["status"] == 429:
                time.sleep(int(rp.get("retryAfter") or 13))
        out["task"] = f"{sudah + baru}/{len(tasks)}"
        if baru:
            msg = f"task {baru} (+{hadiah:.4f})"
            out["note"] = (out["note"] + " | " if out["note"] else "") + msg
            nap()

    # 4) saldo
    think()
    r, tok = get("/overview/users/me/standard", st, tok)
    out["balance"] = (data(r).get("points") or {}).get("totalBalance") or "0.0000"
    return out


# ------------------------------------------------------------- retry -------
def process_with_retry(key, invite, inviter_default):
    """Coba sampai MAX_RETRY kali. Tetap gagal -> dilewati cycle ini,
    dicoba lagi sendiri di cycle berikutnya (akun nggak pernah dibuang)."""
    last = None
    for i in range(1, MAX_RETRY + 1):
        try:
            out = process(key, invite, inviter_default)
        except Exception as exc:
            out = {"code": key[:8], "err": str(exc) or type(exc).__name__}
        if not out.get("err"):
            if i > 1:
                out["note"] = (out["note"] + " | " if out.get("note") else "") + f"ok di percobaan {i}"
            return out
        last = out["err"]
        if i < MAX_RETRY:
            time.sleep(random.uniform(4.0, 18.0) * i)   # mundur pelan-pelan
    return {"code": key[:8], "err": f"{last} (gagal {MAX_RETRY}x, dilewati dulu)"}


# ------------------------------------------------------------------ output --
def baris(o):
    if o.get("err"):
        return f"  {o['code']:<8}  GAGAL  {o['err']}"
    s = (f"  {o['code']:<8}  {o['mining']:<6}  "
         f"saldo {float(o['balance']):>9.4f}  "
         f"reward {float(o.get('reward') or 0):>9.4f}  task {o['task']}")
    if o.get("note"):
        s += f"   [{o['note']}]"
    return s


def emit(text="", stamp=True):
    try:
        print(text, flush=True)
    except Exception:
        pass
    try:
        prefix = (time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()) + "  ") if (stamp and text) else ""
        with open(LOG, "a") as fh:
            fh.write(prefix + text + "\n")
    except Exception:
        pass                                     # disk penuh / log gagal: jangan matiin bot


def cycle():
    accts = read_accounts()
    if not accts:
        emit("accounts.txt kosong — taruh key di situ")
        return
    inviter = read_inviter()
    head = f"{time.strftime('%H:%M UTC', time.gmtime())} — {len(accts)} akun"
    lines, total, ada_error = [], 0.0, False
    order = list(accts)
    random.shuffle(order)                      # urutan akun beda tiap cycle
    for i, (key, inv) in enumerate(order):
        o = process_with_retry(key, inv, inviter)
        lines.append(baris(o))
        if o.get("err"):
            ada_error = True
        else:
            try:
                total += float(o.get("balance") or 0)
            except Exception:
                pass
        if i < len(order) - 1:                 # jeda antar akun, nggak nempel
            time.sleep(random.uniform(2.0, 6.0))
            think(0.15, 3.0, 10.0)

    emit(head, stamp=False)
    for ln in sorted(lines):
        emit(ln)
    if not ada_error:
        emit(f"  total {total:.4f} SST")
    emit()


def next_pause():
    """Istirahat antar cycle — durasinya beda-beda, malam hari lebih jarang."""
    if night():
        return random.randint(1500, 2400)          # 01:00-06:00 WIB: 25-40 menit
    return random.randint(max(300, POLL - 90), POLL + 180)


def main():
    if "--once" in sys.argv:
        cycle()
        return
    backoff = 0
    while True:                                # loop utama: nggak pernah keluar sendiri
        try:
            cycle()
            backoff = 0
        except Exception as exc:
            try:
                emit(f"cycle error: {exc} — coba lagi nanti")
            except Exception:
                pass
            backoff = min(900, max(30, (backoff or 15) * 2))
        try:
            time.sleep(backoff or next_pause())
        except Exception:
            time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("dihentikan manual.")
    except BaseException as exc:               # jaring pengaman terakhir
        try:
            with open(LOG, "a") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}  CRASH: {exc}\n")
        except Exception:
            pass
        raise
