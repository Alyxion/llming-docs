"""Face photo loader and SVG avatar generator for the mock provider.

Standalone implementation -- no office-connect dependency.
Loads JPEG face photos from a configurable directory, or generates
simple SVG circle avatars as a fallback.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Cached face file lists
# ---------------------------------------------------------------------------

_male_faces: list[Path] | None = None
_female_faces: list[Path] | None = None
_cached_dir: Path | None = None


def _resolve_faces_dir(faces_dir: str | None) -> Path | None:
    """Find a valid faces directory from the given path or environment."""
    if faces_dir:
        p = Path(faces_dir)
        if p.is_dir():
            return p
    env = os.environ.get("FACES_DIR", "")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    return None


def _load_face_lists(faces_dir: str | None) -> tuple[list[Path], list[Path]]:
    """Load and cache sorted male/female face file lists."""
    global _male_faces, _female_faces, _cached_dir

    resolved = _resolve_faces_dir(faces_dir)

    # Return cached lists if the directory hasn't changed
    if _male_faces is not None and _cached_dir == resolved:
        return _male_faces, _female_faces  # type: ignore[return-value]

    _cached_dir = resolved
    if resolved and resolved.is_dir():
        _male_faces = sorted(resolved.glob("male_*.jpg"))
        _female_faces = sorted(resolved.glob("female_*.jpg"))
    else:
        _male_faces = []
        _female_faces = []

    return _male_faces, _female_faces


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_face(gender: str, index: int, faces_dir: str | None = None) -> bytes | None:
    """Load a face JPEG by *gender* (``"male"`` / ``"female"``) and *index*.

    Returns ``None`` when no face photos are available (e.g. no faces
    directory configured).
    """
    males, females = _load_face_lists(faces_dir)
    faces = males if gender == "male" else females
    if not faces:
        return None
    path = faces[index % len(faces)]
    return path.read_bytes()


def generate_svg_avatar(initials: str, color: str, size: int = 128) -> bytes:
    """Generate a simple SVG avatar with a colored circle and white initials.

    Returns the SVG as raw UTF-8 bytes.
    """
    font_size = size * 0.4
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{size // 2}" cy="{size // 2}" r="{size // 2}" fill="{color}"/>'
        f'<text x="50%" y="50%" text-anchor="middle" dy=".35em"'
        f' font-family="Arial, sans-serif" font-size="{font_size}" fill="white"'
        f' font-weight="bold">{initials}</text>'
        f'</svg>'
    )
    return svg.encode("utf-8")
