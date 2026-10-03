#!/usr/bin/env python3
"""Sirius multi-account miner — jadwal per akun, bukan polling.

Taruh key di accounts.txt (satu per baris), kode invite di invite.txt.
Jalan terus: ./run.sh          Sekali jalan: ./run.sh --once

Cara kerja: tiap akun dicatat kapan harus dicek lagi (pas reset 24 jam,
atau tiap SIRIUS_TASK_EVERY detik buat task/saldo). Bot tidur sampai
jadwal terdekat — yang lain tetap tidur, jadi nggak ada request sia-sia.
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


BASE = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.environ.get("SIRIUS_ACCOUNTS", os.path.join(BASE, "accounts.txt"))
INVITE_FILE = os.environ.get("SIRIUS_INVITE", os.path.join(BASE, "invite.txt"))
STATE_DIR = os.path.join(BASE, "accounts")
LOG = os.path.join(BASE, "log.txt")
MAX_RETRY = max(1, int(os.environ.get("SIRIUS_RETRY", "3")))
TASK_EVERY = max(600, int(os.environ.get("SIRIUS_TASK_EVERY", "21600")))  # task+saldo tiap 6 jam
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
        # token ditolak server (expired / dicabut session lain) → buang, paksa ambil baru
        st["accessToken"] = None
        save_state(st)
        time.sleep(random.uniform(1.0, 3.0))
        tok = ensure_token(st)
        return get(path, st, tok, _retry=False)
    return r, tok


# ------------------------------------------------------------- satu akun ----
def parse_ts(s):
    """'2026-10-04T15:18:00Z' -> epoch detik."""
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).replace(
            tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


def process(key, invite_override, inviter_default, force=False):
    st = load_state(key)
    invite = invite_override or st.get("inviterCode") or inviter_default
    out = {"code": st.get("userCode") or key[:8], "note": "", "err": None}
    now = time.time()

    def atur_jadwal(reset_at):
        """Catat kapan akun ini harus dicek lagi — inilah hitung mundurnya."""
        # TASK_EVERY dikasih jeda acak 0-45 menit biar ratusan akun nggak
        # bangun di detik yang sama (dibagi jadi batch kecil sepanjang waktu)
        kandidat = [now + TASK_EVERY + random.uniform(0.0, 2700.0)]
        if reset_at:
            kandidat.append(reset_at + random.uniform(45.0, 300.0))
        st["nextCheckAt"] = min(kandidat)
        save_state(st)

    tok = ensure_token(st)

    # 1) profil + pasang kode invite (sekali aja, sisanya pakai cache)
    if force or not st.get("userCode") or not st.get("invitationBound"):
        r, tok = get("/users/me", st, tok)
        if r["status"] != 200:
            out["err"] = f"login {r['status']} {err(r) or ''}".strip()
            return out
        me = data(r)
        st["userCode"] = me.get("userCode")
        st["userId"] = me.get("userId")
        st["invitationBound"] = bool(me.get("invitationBound"))
        save_state(st)
        out["code"] = st.get("userCode") or key[:8]

    if not st.get("invitationBound"):
        if not invite:
            out["note"] = "invite belum diisi (isi invite.txt)"
        else:
            nap()
            rb = api.call("POST", "/users/me/inviter", {"inviterCode": invite}, token=tok)
            if rb["status"] == 200:
                st["invitationBound"] = True
                out["note"] = "invite dipasang"
                save_state(st)
            else:
                out["err"] = f"invite {rb['status']} {err(rb) or ''}".strip()
                atur_jadwal(None)
                return out
            nap()
    if invite and st.get("inviterCode") != invite:
        st["inviterCode"] = invite
        save_state(st)

    # 2) mining — cek status dulu, baru putuskan perlu start apa nggak
    nap()
    r, tok = get("/mining/tasks/status", st, tok)
    if r["status"] != 200:
        out["err"] = f"status {r['status']} {err(r) or ''}".strip()
        atur_jadwal(None)
        return out
    d = data(r)
    ms = d.get("miningStatus")
    out["reward"] = d.get("totalMiningReward") or "0.0000"
    reset_at = parse_ts(d.get("largeCycleEndsAt")) if ms == "RUNNING" else None

    if ms != "RUNNING":
        time.sleep(random.uniform(3.0, 15.0))       # nggak langsung ngebut
        rs = api.call("POST", "/mining/tasks/start", {}, token=tok)
        if rs["status"] == 200:
            out["started"] = True
            out["note"] = (out["note"] + " | " if out["note"] else "") + "mining dimulai"
            out["reward"] = "0.0000"
        else:
            out["err"] = f"mulai mining {rs['status']} {err(rs) or ''}".strip()
            atur_jadwal(None)
            return out
        nap()
        r, tok = get("/mining/tasks/status", st, tok)
        if r["status"] == 200:
            d = data(r)
            ms = d.get("miningStatus")
            out["reward"] = d.get("totalMiningReward") or "0.0000"
            reset_at = parse_ts(d.get("largeCycleEndsAt")) if ms == "RUNNING" else None
    out["mining"] = "jalan" if ms == "RUNNING" else (ms or "?").lower()

    # 3) task + saldo — cukup TASK_EVERY sekali, bukan tiap cycle
    out["task"] = st.get("task") or "-"
    out["balance"] = st.get("balance") or "0.0000"
    perlu_full = force or not st.get("lastFullCheck") or \
        (now - float(st.get("lastFullCheck") or 0)) >= TASK_EVERY

    if perlu_full and st.get("runTasks", True):
        nap()
        rl, tok = get("/tasks", st, tok)
        if rl["status"] == 200:
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
            st["task"] = out["task"]
            save_state(st)
            if baru:
                msg = f"task {baru} (+{hadiah:.4f})"
                out["note"] = (out["note"] + " | " if out["note"] else "") + msg
                nap()

        think()
        r, tok = get("/overview/users/me/standard", st, tok)
        if r["status"] == 200:
            out["balance"] = (data(r).get("points") or {}).get("totalBalance") or "0.0000"
            st["balance"] = out["balance"]
        st["lastFullCheck"] = time.time()
        save_state(st)

    atur_jadwal(reset_at)
    return out


# ------------------------------------------------------------- retry -------
def process_with_retry(key, invite, inviter_default, force=False):
    """Coba sampai MAX_RETRY kali. Tetap gagal -> dilewati dulu,
    dicoba lagi ~10 menit kemudian (akun nggak pernah dibuang)."""
    last = None
    for i in range(1, MAX_RETRY + 1):
        try:
            out = process(key, invite, inviter_default, force)
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
    if o.get("i"):
        s = f"Account {o['i']}/{o['n']}  {o['code']}"
        head = f"{s}  {'.' * max(3, 30 - len(s))}  "
    else:
        head = "  "
    if o.get("err"):
        return f"{head}Failed — {o['err']}"
    word = "Mining success" if o.get("started") else "Already mining (skipped)"
    line = f"{head}{word}   saldo {float(o.get('balance') or 0):.4f}   task {o.get('task', '-')}"
    if float(o.get("reward") or 0):
        line += f"   reward {float(o['reward']):.4f}"
    if o.get("note"):
        line += f"   [{o['note']}]"
    return line


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


def kosongkan_log():
    try:
        with open(LOG, "w"):
            pass
    except Exception:
        pass


# --------------------------------------------------------------- jadwal -----
def jadwal_berikutnya(accts):
    """Waktu terdekat di antara semua akun harus dicek lagi."""
    t = None
    for key, _ in accts:
        try:
            v = float(load_state(key).get("nextCheckAt") or 0)
        except Exception:
            continue
        if v > 0 and (t is None or v < t):
            t = v
    return t


def jam(ts):
    if not ts:
        return "-"
    sisa = max(0, int(ts - time.time()))
    jm, menit = divmod(sisa // 60, 60)
    head = time.strftime("%H:%M UTC", time.gmtime(ts))
    return f"{head} ({jm}j {menit}m lagi)" if jm else f"{head} ({menit}m lagi)"


def cycle(force=False):
    accts = read_accounts()
    if not accts:
        kosongkan_log()
        emit("accounts.txt kosong — taruh key di situ", stamp=False)
        return None

    now = time.time()
    # cuma akun yang jatuh tempo yang disentuh — yang lain tetap tidur
    order = [(k, inv) for k, inv in accts
             if force or float(load_state(k).get("nextCheckAt") or 0) <= now]
    if not order:
        return jadwal_berikutnya(accts)            # belum ada yang waktunya — senyap

    inviter = read_inviter()
    random.shuffle(order)                          # urutan akun beda tiap cycle
    n = len(order)
    t0 = time.time()

    kosongkan_log()    # log cuma nyimpen 1 cycle terakhir — yang lama dibersihkan
    emit(f"Bot starting... {n} akun dicek  ({time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())})",
         stamp=False)

    total, jalan, gagal = 0.0, 0, 0
    for i, (key, inv) in enumerate(order, 1):
        o = process_with_retry(key, inv, inviter, force)
        o["i"], o["n"] = i, n
        emit(baris(o), stamp=False)                # langsung keluar, nggak nunggu selesai
        if o.get("err"):
            gagal += 1
            try:                                   # gagal -> coba lagi ~10 menit lagi
                st = load_state(key)
                st["nextCheckAt"] = time.time() + random.uniform(300.0, 900.0)
                save_state(st)
            except Exception:
                pass
        else:
            jalan += 1
            try:
                total += float(o.get("balance") or 0)
            except Exception:
                pass
        if i < n:                                  # jeda antar akun, nggak nempel
            time.sleep(random.uniform(2.0, 6.0))
            think(0.15, 3.0, 10.0)

    dur = int(time.time() - t0)
    nxt = jadwal_berikutnya(accts)
    emit(f"Done — {jalan} success, {gagal} failed — total {total:.4f} SST ({dur}s) "
         f"— cek berikutnya {jam(nxt)}", stamp=False)
    emit()
    return nxt


# ------------------------------------------------------------------- main ---
def main():
    if "--once" in sys.argv:
        cycle(force=True)
        return

    # biar keliatan bot-nya ngapain pas nyala (kalau belum ada yang jatuh tempo)
    try:
        accts = read_accounts()
        ada_due = any(float(load_state(k).get("nextCheckAt") or 0) <= time.time() for k, _ in accts)
        if accts and not ada_due:
            kosongkan_log()
            emit(f"Bot nyala — {len(accts)} akun, semua lagi tidur", stamp=False)
            emit(f"Jadwal cek berikutnya: {jam(jadwal_berikutnya(accts))}", stamp=False)
            emit("(diam dulu ya, nanti bangun sendiri pas waktunya)", stamp=False)
            emit()
    except Exception:
        pass

    backoff = 0
    while True:                                    # loop utama: nggak pernah keluar sendiri
        nxt = None
        try:
            nxt = cycle()
            backoff = 0
        except Exception as exc:
            try:
                emit(f"cycle error: {exc} — coba lagi nanti")
            except Exception:
                pass
            backoff = min(900, max(30, (backoff or 15) * 2))

        try:
            if backoff:
                tidur = backoff
            else:
                # tidur sampai jadwal terdekat, tapi paling lama 3-6 menit sekali
                # (bangun cuma buat baca accounts.txt — lokal, tanpa request)
                now = time.time()
                batas = random.randint(180, 360)
                tidur = min(nxt - now, batas) if (nxt and nxt > now) else batas
                tidur = max(15.0, tidur)
            time.sleep(tidur)
        except Exception:
            time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("dihentikan manual.")
    except BaseException as exc:                   # jaring pengaman terakhir
        try:
            with open(LOG, "a") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}  CRASH: {exc}\n")
        except Exception:
            pass
        raise
