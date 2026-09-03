from collections.abc import Iterator


def camera_index(camera_id: str) -> int:
    prefix, _, value = camera_id.partition(":")
    if prefix != "opencv" or not value.isdigit():
        raise ValueError(f"Unsupported camera id: {camera_id}")
    return int(value)


def mjpeg_stream(camera_id: str) -> Iterator[bytes]:
    import cv2

    camera = cv2.VideoCapture(camera_index(camera_id))
    if not camera.isOpened():
        camera.release()
        raise RuntimeError(f"Unable to open camera: {camera_id}")
    try:
        while True:
            success, frame = camera.read()
            if not success:
                break
            success, encoded = cv2.imencode(".jpg", frame)
            if success:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
    finally:
        camera.release()
