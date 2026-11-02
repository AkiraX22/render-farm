"""Render farm controller: prepares NATS and splits a render job into tiles."""

import argparse
import asyncio
import json
import os
import uuid

import nats
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StreamConfig

NATS_URL = os.environ.get("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
STREAM = "TILES"
CONSUMER = "workers"
SUBJECT = "render.tiles"


async def setup(js):
    await js.add_stream(
        StreamConfig(
            name=STREAM,
            subjects=[f"{SUBJECT}.>"],
            retention=RetentionPolicy.WORK_QUEUE,
        )
    )
    await js.add_consumer(
        STREAM,
        ConsumerConfig(
            durable_name=CONSUMER,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=60,
            max_deliver=5,
            filter_subject=f"{SUBJECT}.>",
        ),
    )
    print(f"stream {STREAM} and consumer {CONSUMER} ready")


def make_job(args):
    return {
        "job": args.job or uuid.uuid4().hex[:8],
        "width": args.width,
        "height": args.height,
        "tile": args.tile,
        "max_iter": args.max_iter,
        "cx": args.cx,
        "cy": args.cy,
        "scale": args.scale,
    }


async def submit(js, job):
    count = 0
    for y in range(0, job["height"], job["tile"]):
        for x in range(0, job["width"], job["tile"]):
            tile = dict(
                job,
                x=x,
                y=y,
                w=min(job["tile"], job["width"] - x),
                h=min(job["tile"], job["height"] - y),
            )
            await js.publish(f"{SUBJECT}.{job['job']}", json.dumps(tile).encode())
            count += 1
    print(f"job {job['job']}: {count} tiles submitted")
    return count


async def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    submit_p = sub.add_parser("submit")
    submit_p.add_argument("--job")
    submit_p.add_argument("--width", type=int, default=1920)
    submit_p.add_argument("--height", type=int, default=1080)
    submit_p.add_argument("--tile", type=int, default=64)
    submit_p.add_argument("--max-iter", type=int, default=2000)
    submit_p.add_argument("--cx", type=float, default=-0.743643887)
    submit_p.add_argument("--cy", type=float, default=0.131825904)
    submit_p.add_argument("--scale", type=float, default=0.003)
    args = parser.parse_args()

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    try:
        if args.cmd == "setup":
            await setup(js)
        elif args.cmd == "submit":
            await submit(js, make_job(args))
    finally:
        await nc.close()


if __name__ == "__main__":
    asyncio.run(main())
