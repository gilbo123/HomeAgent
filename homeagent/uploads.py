"""Image upload handling.

* Parses multipart/form-data using only the standard library
  (``email.message`` does a fully spec-compliant multipart parser for us).
* Stores each image under a random 32-hex name (``<uuid>.<ext>``) in the
  configured upload directory, so names can never collide or be guessed.
* Validates both the part's MIME type *and* the file extension against a
  small allow-list, and enforces a size cap.

The DB stores only the file name; :class:`UploadStore` resolves names to
absolute paths so the DB layer never deals with the upload directory.
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from email import message_from_bytes
from email import policy as email_policy

# MIME type -> canonical extension. Anything else is rejected.
ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

_FILENAME_RE = re.compile(r"[0-9a-f]{32}\.[a-z0-9]{2,5}$", re.IGNORECASE)


class UploadError(Exception):
    """Base class for upload problems (message is user-facing)."""


class UploadTooLarge(UploadError):
    pass


class UnsupportedImage(UploadError):
    pass


class MissingFilePart(UploadError):
    pass


class UploadStore:
    """Stores and resolves uploaded images."""

    def __init__(self, upload_dir: str, max_image_mb: int) -> None:
        self.upload_dir = upload_dir
        self.max_bytes = max_image_mb * 1024 * 1024
        os.makedirs(self.upload_dir, exist_ok=True)

    # ------------------------------------------------------------------ api

    def store(self, body: bytes, content_type: str) -> str:
        """Validate + persist one uploaded image; returns the stored name.

        Raises UploadError subclasses on any problem.
        """
        if len(body) > self.max_bytes:
            raise UploadTooLarge(
                f"Image too large (max {self.max_bytes // (1024 * 1024)} MB)"
            )
        name, data = _first_file_part(body, content_type)
        if name is None or data is None:
            raise MissingFilePart("No image file found in upload")

        mime = content_type.split(";", 1)[0].strip().lower()
        ext = _pick_extension(name, mime)
        if ext is None:
            raise UnsupportedImage(
                "Unsupported image type (allowed: "
                + ", ".join(sorted(ALLOWED_IMAGE_TYPES))
                + ")"
            )

        stored = uuid.uuid4().hex + ext
        with open(os.path.join(self.upload_dir, stored), "wb") as f:
            f.write(data)
        return stored

    def path_for(self, name: str) -> str:
        """Absolute path for a stored name, or "" if not found/valid."""
        if not _FILENAME_RE.match(name):
            return ""
        path = os.path.normpath(os.path.join(self.upload_dir, name))
        # Defence in depth: never allow traversal out of upload_dir.
        if not path.startswith(os.path.normpath(self.upload_dir) + os.sep):
            return ""
        return path if os.path.isfile(path) else ""

    def content_type_for(self, name: str) -> str:
        ext = os.path.splitext(name)[1].lower()
        return {v: k for k, v in ALLOWED_IMAGE_TYPES.items()}.get(ext, "application/octet-stream")


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

def _first_file_part(body: bytes, content_type: str) -> tuple[str | None, bytes | None]:
    """Extract the first file part from a multipart/form-data body."""
    if not content_type.lower().startswith("multipart/form-data"):
        return None, None
    # The standard library's email parser works on a single message; give it
    # the body with its Content-Type re-attached as the header.
    raw = b"Content-Type: " + content_type.encode("latin-1", "replace") + b"\r\n\r\n" + body
    try:
        msg = message_from_bytes(raw, policy=email_policy.default)
        for part in msg.iter_parts():
            filename = part.get_filename()
            data = part.get_payload(decode=True)
            if filename and data:
                return filename, data
    except Exception:
        pass  # malformed multipart — treated as "no file part"
    return None, None


def _pick_extension(filename: str, mime: str) -> str | None:
    """Choose an extension from MIME or filename; None if not allowed."""
    # Trust the declared MIME when it is in the allow-list.
    if mime in ALLOWED_IMAGE_TYPES:
        return ALLOWED_IMAGE_TYPES[mime]
    # Otherwise fall back to the extension, if it is in the allow-list.
    ext = mimetypes.guess_extension(mime) if mime else None
    if ext == ".jpe":
        ext = ".jpg"
    if ext and ext in ALLOWED_IMAGE_TYPES.values():
        return ext
    m = re.search(r"\.([a-z0-9]{2,5})$", filename.lower())
    if m and "." + m.group(1) in ALLOWED_IMAGE_TYPES.values():
        return "." + m.group(1)
    return None
