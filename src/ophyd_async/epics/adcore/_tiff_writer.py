from ._core_writer import ADWriter


class ADTIFFWriter(ADWriter):
    def __init__(
        self,
        *args,
    ) -> None:
        super().__init__(
            *args, file_extension=".tiff", mimetype="multipart/related;type=image/tiff"
        )
        self.tiff = self.fileio
