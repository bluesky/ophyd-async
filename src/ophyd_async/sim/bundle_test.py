from pathlib import Path
from typing import Iterator
from event_model import (
    ComposeStreamResource,
    ComposeStreamResourceBundle,
    StreamDatum,
    StreamRange,
)


def main():
    bundler_composer = ComposeStreamResource()

    path: Path = Path("root")
    bundle: ComposeStreamResourceBundle = bundler_composer(
        spec="test",
        root="root",
        resource_path=str(path),
        data_key="name",
        resource_kwargs={
            "path": str(path.as_posix()),
            "multiplier": 1,
            "timestamps": "/entry/instrument/NDAttributes/NDArrayTimeStamp",
        },
    )
    indices_range = StreamRange(start=0, stop=1)

    def compose(b: ComposeStreamResourceBundle):
        yield b.compose_stream_datum(indices_range)

    iterator: Iterator[StreamDatum] = [compose(b) for b in [bundle]]
    print(iterator)


if __name__ == "__main__":
    main()
