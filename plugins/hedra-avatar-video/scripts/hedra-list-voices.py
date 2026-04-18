#!/usr/bin/env python3
"""List Hedra voices, optionally filtered by gender/accent/age."""
import argparse
import os
import sys

import requests

BASE_URL = "https://api.hedra.com/web-app/public"


def load_api_key() -> str:
    key = os.environ.get("HEDRA_API_KEY")
    if key:
        return key.strip()
    key_file = "/Users/sethward/GIT/Squidgy/.hedra-api-key"
    if os.path.exists(key_file):
        with open(key_file) as f:
            return f.read().strip()
    print("error: HEDRA_API_KEY not set and .hedra-api-key not found", file=sys.stderr)
    sys.exit(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--gender", help="male|female")
    p.add_argument("--accent", help="e.g. american, british (case-insensitive substring)")
    p.add_argument("--age", help="young|adult|middle aged|old")
    args = p.parse_args()

    r = requests.get(f"{BASE_URL}/voices", headers={"x-api-key": load_api_key()})
    r.raise_for_status()
    voices = r.json()

    def match(v):
        labels = {l["name"].lower(): l["value"].lower() for l in v["asset"]["labels"]}
        if args.gender and labels.get("gender") != args.gender.lower():
            return False
        if args.accent and args.accent.lower() not in labels.get("accent", ""):
            return False
        if args.age and labels.get("age") != args.age.lower():
            return False
        return True

    filtered = [v for v in voices if match(v)]
    print(f"{'ID':<40}  {'Name':<15}  {'Gender':<8}  {'Accent':<12}  {'Age':<13}  Description")
    print("-" * 140)
    for v in filtered:
        labels = {l["name"]: l["value"] for l in v["asset"]["labels"]}
        print(f"{v['id']:<40}  {v['name']:<15}  {labels.get('gender','-'):<8}  "
              f"{labels.get('accent','-'):<12}  {labels.get('age','-'):<13}  "
              f"{(v.get('description') or '')[:70]}")
    print(f"\n{len(filtered)} / {len(voices)} voices")


if __name__ == "__main__":
    main()
