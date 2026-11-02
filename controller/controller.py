"""Render farm controller: prepares NATS and MinIO, splits jobs into tiles, assembles results."""

import argparse
import asyncio
import io
import json
import os
import re
import time
import uuid

import nats
from minio import Minio
from nats.js.api import AckPolicy, ConsumerConfig, RetentionPolicy, StreamConfig
from PIL import Image

NATS_URL = os.environ.get("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
STREAM = "TILES"
CONSUMER = "workers"
SUBJECT = "render.tiles"
BUCKET = os.environ.get("MINIO_BUCKET", "renders")


def minio_client():
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://minio.minio.svc.cluster.local:9000")
    return Minio(
        re.sub(r"^https?://", "", endpoint),
        access_key=os.environ["MINIO_ROOT_USER"],
        secret_key=os.environ["MINIO_ROOT_PASSWORD"],
        secure=endpoint.startswith("https://"),
        region="us-east-1",
    )


async def setup(js, s3):
    if not s3.bucket_exists(BUCKET):
        s3.make_bucket(BUCKET)
    print(f"bucket {BUCKET} ready")
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
    job_id = args.job or uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[a-z0-9-]{1,40}", job_id):
        raise SystemExit("job id must match [a-z0-9-]{1,40}")
    return {
        "job": job_id,
        "width": args.width,
        "height": args.height,
        "tile": args.tile,
        "max_iter": args.max_iter,
        "cx": args.cx,
        "cy": args.cy,
        "scale": args.scale,
    }


def put_bytes(s3, key, data, content_type):
    s3.put_object(BUCKET, key, io.BytesIO(data), len(data), content_type=content_type)


async def submit(js, s3, job):
    tiles = [
        dict(job, x=x, y=y, w=min(job["tile"], job["width"] - x), h=min(job["tile"], job["height"] - y))
        for y in range(0, job["height"], job["tile"])
        for x in range(0, job["width"], job["tile"])
    ]
    # Written first so an assembler can start as soon as the tiles are queued.
    put_bytes(s3, f"jobs/{job['job']}/job.json", json.dumps(dict(job, tiles=len(tiles))).encode(), "application/json")
    for tile in tiles:
        await js.publish(f"{SUBJECT}.{job['job']}", json.dumps(tile).encode())
    print(f"job {job['job']}: {len(tiles)} tiles submitted")


def assemble(s3, job_id, timeout):
    job = json.loads(s3.get_object(BUCKET, f"jobs/{job_id}/job.json").read())
    prefix = f"jobs/{job_id}/tiles/"
    deadline = time.monotonic() + timeout
    while True:
        keys = [o.object_name for o in s3.list_objects(BUCKET, prefix=prefix)]
        print(f"job {job_id}: {len(keys)}/{job['tiles']} tiles rendered")
        if len(keys) >= job["tiles"]:
            break
        if time.monotonic() > deadline:
            raise SystemExit(f"job {job_id}: timed out waiting for tiles")
        time.sleep(2)

    image = Image.new("RGB", (job["width"], job["height"]))
    for key in keys:
        x, y = map(int, key.rsplit("/", 1)[1].removesuffix(".ppm").split("_"))
        resp = s3.get_object(BUCKET, key)
        try:
            image.paste(Image.open(io.BytesIO(resp.read())), (x, y))
        finally:
            resp.close()
            resp.release_conn()

    out = io.BytesIO()
    image.save(out, format="PNG")
    key = f"jobs/{job_id}/final.png"
    put_bytes(s3, key, out.getvalue(), "image/png")
    print(f"job {job_id}: assembled s3://{BUCKET}/{key}")


async def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    submit_p = sub.add_parser("submit")
    render_p = sub.add_parser("render", help="submit, then wait and assemble")
    assemble_p = sub.add_parser("assemble")
    assemble_p.add_argument("--job", required=True)
    for p in (submit_p, render_p):
        p.add_argument("--job")
        p.add_argument("--width", type=int, default=1920)
        p.add_argument("--height", type=int, default=1080)
        p.add_argument("--tile", type=int, default=64)
        p.add_argument("--max-iter", type=int, default=2000)
        p.add_argument("--cx", type=float, default=-0.743643887)
        p.add_argument("--cy", type=float, default=0.131825904)
        p.add_argument("--scale", type=float, default=0.003)
    for p in (render_p, assemble_p):
        p.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    s3 = minio_client()
    if args.cmd == "assemble":
        assemble(s3, args.job, args.timeout)
        return

    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    try:
        if args.cmd == "setup":
            await setup(js, s3)
        else:
            job = make_job(args)
            await submit(js, s3, job)
    finally:
        await nc.close()
    if args.cmd == "render":
        assemble(s3, job["job"], args.timeout)


if __name__ == "__main__":
    asyncio.run(main())
