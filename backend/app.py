import json
import queue
import threading
import logging
import sys
from pathlib import Path

from flask import Flask, jsonify
from flask_sock import Sock

sys.path.insert(0, str(Path(__file__).parent))

from engine import TradingEngine
from data.morning_brief import get_morning_brief

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
sock = Sock(app)

engine = TradingEngine()
_ws_queues: list[queue.Queue] = []
_ws_lock = threading.Lock()


def _broadcast(state: dict):
    payload = json.dumps(state)
    with _ws_lock:
        dead = []
        for q in _ws_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _ws_queues.remove(q)


# ------------------------------------------------------------------
# REST endpoints
# ------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/state")
def get_state():
    return jsonify(engine.get_state())


@app.route("/api/battle")
def get_battle():
    return jsonify(engine.get_battle_info())


@app.route("/api/divisions")
def get_divisions():
    return jsonify(engine.get_divisions())


@app.route("/api/brief")
def get_brief():
    brief_obj = get_morning_brief()
    prices    = engine._last_prices or {}
    brief     = brief_obj.get_brief(prices)
    return jsonify(brief)


@app.route("/api/liquidite")
def get_liquidite():
    from divisions.middle_office import get_liquidity_desk
    desk = get_liquidity_desk()
    data = desk.get_data()
    return jsonify({
        "global_liquidity_score": data.get("global_liquidity_score"),
        "regime":                 data.get("regime"),
        "agent_scores":           data.get("agent_scores", {}),
        "agent_summaries":        data.get("agent_summaries", {}),
        "alerts":                 data.get("alerts", []),
        "errors":                 data.get("errors", []),
        "timestamp":              data.get("timestamp"),
        "bertez_signal":          data.get("bertez_signal"),
        "bertez_mode":            data.get("bertez_mode"),
    })


@app.route("/api/liquidite/refresh", methods=["POST"])
def trigger_liquidite_refresh():
    from divisions.middle_office import get_liquidity_desk
    get_liquidity_desk().trigger_background_refresh()
    return jsonify({"status": "refresh triggered"})


@app.route("/api/weekly-agent")
def get_weekly_agent():
    return jsonify(engine.get_weekly_agent())


@app.route("/api/post-market")
def get_post_market():
    return jsonify(engine.get_post_market())


@app.route("/api/maintenance/health")
def get_maintenance_health():
    from maintenance import get_health as _health
    from config import DB_PATH
    return jsonify(_health(engine, DB_PATH, len(_ws_queues)))


@app.route("/api/trader/<int:trader_id>")
def get_trader(trader_id: int):
    data = engine.get_trader(trader_id)
    if data is None:
        return jsonify({"error": "Trader not found"}), 404
    return jsonify(data)


# ------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------

@sock.route("/ws")
def websocket(ws):
    q: queue.Queue = queue.Queue(maxsize=20)
    with _ws_lock:
        _ws_queues.append(q)
    # Push current state immediately on connect
    ws.send(json.dumps(engine.get_state()))
    try:
        while True:
            # Block until a tick update arrives; timeout keeps the loop alive
            try:
                msg = q.get(timeout=30)
                ws.send(msg)
            except queue.Empty:
                # Send a heartbeat so the client knows we're still alive
                ws.send(json.dumps({"type": "heartbeat"}))
    except Exception:
        pass
    finally:
        with _ws_lock:
            if q in _ws_queues:
                _ws_queues.remove(q)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    engine.set_tick_callback(_broadcast)
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()
    logger.info("Server starting on http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
