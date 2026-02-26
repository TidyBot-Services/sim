"""sim_server — MuJoCo simulation server for TidyBot.

Implements the same network protocols as the real hardware servers
(ZMQ, RPC, WebSocket) so the agent_server's backends can connect
transparently to either real hardware or simulation.

Start with:
    python -m sim_server
"""
