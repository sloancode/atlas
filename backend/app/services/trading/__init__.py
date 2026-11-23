"""Autonomous PAPER trading bot: fixed trend-following rules + code-enforced risk limits.

The planner is pure: it reads broker state + daily bars and returns the exact orders to
place. It never talks to a broker itself and refuses to run against a live account.
"""
