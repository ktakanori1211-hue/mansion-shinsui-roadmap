"""デモ 2 地点で、公開データが今も読めるかを確かめる。python3 -m scripts.check_location"""

from app.location import read_location
from app.server import DEMO_POINTS


def main() -> None:
    for point in DEMO_POINTS.values():
        print(f"\n== {point['label']} ({point['longitude']}, {point['latitude']})")
        for distance in (25, 50, 100):
            result = read_location(point["longitude"], point["latitude"], distance)
            values = {p["key"]: p["elevation_m"] for p in result["elevation"]["points"]}
            print(f"標高 {distance}m: {values} / {result['elevation']['points'][0]['source']}")
        for hazard in result["hazards"]:
            print(f"{hazard['label']}: {hazard['status']} {hazard['legend'] or ''}")
        for landform in result["landforms"]:
            print(f"{landform['label']}: {landform['status']} {landform['codes']} {landform['names']}")


if __name__ == "__main__":
    main()
