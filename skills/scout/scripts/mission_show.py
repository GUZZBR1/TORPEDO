#!/usr/bin/env python3
from scout_db import ScoutError, cli, latest_active_mission, show_mission


def handle(data, path):
    if data.get("latest_active") is True:
        if set(data) != {"latest_active"}:
            raise ScoutError("latest_active cannot be combined with other fields")
        return latest_active_mission(path)
    return show_mission(data, path)


if __name__ == "__main__":
    cli(handle)
