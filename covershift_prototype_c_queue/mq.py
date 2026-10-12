"""メッセージキュー(SQS API)の薄い道具。ElasticMQ でも、本物のSQSでも、endpointを変えるだけで動く想定。"""
import json
import time

import boto3
from botocore.config import Config

from . import config

_client = None


def client():
    global _client
    if _client is None:
        _client = boto3.client(
            "sqs", endpoint_url=config.SQS_ENDPOINT, region_name="us-east-1",
            aws_access_key_id="x", aws_secret_access_key="x",
            config=Config(retries={"max_attempts": 1}, connect_timeout=3, read_timeout=config.QUEUE_WAIT_SEC + 10),
        )
    return _client


def ensure_queue(name: str) -> str:
    """キューと、その隔離キュー(name-dlq)を(なければ)作り、キューのURLを返す。何度呼んでも同じ。"""
    c = client()
    for attempt in range(10):
        try:
            dlq = c.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
            arn = c.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
            attrs = {
                "VisibilityTimeout": str(config.VISIBILITY_TIMEOUT_SEC),
                "RedrivePolicy": json.dumps({"deadLetterTargetArn": arn, "maxReceiveCount": str(config.MAX_RECEIVE)}),
            }
            try:
                url = c.create_queue(QueueName=name, Attributes=attrs)["QueueUrl"]
            except Exception:
                url = c.get_queue_url(QueueName=name)["QueueUrl"]
                c.set_queue_attributes(QueueUrl=url, Attributes=attrs)
            return url
        except Exception:
            if attempt == 9:
                raise
            time.sleep(1)
    raise RuntimeError("unreachable")


def send(url: str, body: dict, delay: int = 0) -> None:
    client().send_message(QueueUrl=url, MessageBody=json.dumps(body, ensure_ascii=False), DelaySeconds=delay)


def receive(url: str, wait: int | None = None) -> list[dict]:
    r = client().receive_message(
        QueueUrl=url, MaxNumberOfMessages=1, WaitTimeSeconds=config.QUEUE_WAIT_SEC if wait is None else wait,
        AttributeNames=["ApproximateReceiveCount"],
    )
    return r.get("Messages", [])


def delete(url: str, msg: dict) -> None:
    client().delete_message(QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"])


def release(url: str, msg: dict) -> None:
    """処理に失敗したメッセージを、待たずにすぐ見える状態へ戻す(期限切れを待つと、そのぶん遅れるため)。失敗しても無視。"""
    try:
        client().change_message_visibility(QueueUrl=url, ReceiptHandle=msg["ReceiptHandle"], VisibilityTimeout=0)
    except Exception:
        pass
