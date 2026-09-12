#!/usr/bin/env python3
from scout_db import cli, latest_active_mission, show_mission


def handle(data, path):
    if data.get("latest_active") is True:
        return latest_active_mission(path)
    return show_mission(data, path)


if __name__ == "__main__":
    cli(handle)

