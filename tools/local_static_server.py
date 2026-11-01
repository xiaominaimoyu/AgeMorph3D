"""Serve one built frontend directory on loopback. This is not the API.

The process binds 127.0.0.1 only and refuses paths that leave the directory.
It does not install packages, read model manifests, or grant readiness.
"""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"


class StaticHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs) -> None:
        self.static_root = Path(directory).resolve()
        super().__init__(*args, directory=str(self.static_root), **kwargs)

    def translate_path(self, path: str) -> str:
        translated = Path(super().translate_path(path)).resolve()
        if not translated.is_relative_to(self.static_root):
            return str(self.static_root / ".outside")
        return str(translated)

    def _serve_index_for_directory(self) -> None:
        translated = Path(self.translate_path(self.path))
        if translated.is_dir():
            index = translated / "index.html"
            if not index.is_file():
                self.send_error(404, "Directory listing is disabled.")
                return
            suffix = "" if self.path.endswith("/") else "/"
            self.path = f"{self.path}{suffix}index.html"
        super().do_GET()

    def do_GET(self) -> None:
        self._serve_index_for_directory()

    def list_directory(self, path: str):
        del path
        self.send_error(404, "Directory listing is disabled.")
        return None


class StaticServer(ThreadingHTTPServer):
    allow_reuse_address = True


def serve(directory: Path, port: int, host: str = HOST) -> None:
    if host != HOST:
        raise ValueError("The static frontend binds 127.0.0.1 only.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Port must be an integer from 1 to 65535.")
    root = directory.resolve()
    if not root.is_dir():
        raise ValueError("The built frontend directory does not exist.")
    server = StaticServer((host, port), partial(StaticHandler, directory=str(root)))
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the built frontend on 127.0.0.1.")
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        serve(args.directory, args.port, args.host)
    except ValueError as error:
        parser.exit(2, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
