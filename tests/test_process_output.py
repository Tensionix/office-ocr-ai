"""What a program the engine runs writes reaches the terminal as text, whatever encoding it writes in.

The engine reads the output of a program that is not Python as one stream of chunks, each ending
at the byte \\n, as a pipe gives them (system_core\\core\\output_decode.py, ProcessText): UTF-8 with
or without its mark, the OEM page (cp866), the ANSI one (cp1251), UTF-16 of either byte order with
or without its mark, and a script that runs one such program after another.
"""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

from system_core.core.jobs import decoded_process_lines
from system_core.core.output_decode import ProcessText

LINES = ["Распознано страниц: 3", "Ошибка: файл не найден", "Done."]


def read(data: bytes) -> list[str]:
    """The lines the terminal gets from these bytes, cut as a pipe cuts them."""
    stream, lines = ProcessText(), []
    for chunk in io.BufferedReader(io.BytesIO(data)):
        lines += decoded_process_lines(stream.feed(chunk))
    return lines + decoded_process_lines(stream.close())


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp866", "cp1251", "utf-16-le", "utf-16", "utf-16-be"])
def test_every_encoding_reads_as_text(encoding: str) -> None:
    assert read(("\r\n".join(LINES) + "\r\n").encode(encoding)) == LINES


def test_a_script_that_runs_one_program_after_another() -> None:
    data = "Шаг 1\r\n".encode("cp866") + "Таблица ГПУ\r\nNVIDIA\r\n".encode("utf-16") + "Готово\r\n".encode("utf-8")
    assert read(data) == ["Шаг 1", "Таблица ГПУ", "NVIDIA", "Готово"]


def test_utf16_of_cyrillic_alone_without_its_mark() -> None:
    # No NUL in the first line: it is told by the high byte of Cyrillic, 0x04 at every other place.
    assert read("Привет\nМир\n".encode("utf-16-le")) == ["Привет", "Мир"]


@pytest.mark.skipif(sys.platform != "win32", reason="cmd /u is of Windows")
def test_cmd_writing_utf16_into_a_pipe_reads_as_text() -> None:
    process = subprocess.Popen(["cmd.exe", "/d", "/u", "/c", "echo Привет& echo Мир"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert process.stdout is not None
    stream, lines = ProcessText(), []
    for chunk in process.stdout:
        lines += decoded_process_lines(stream.feed(chunk))
    lines += decoded_process_lines(stream.close())
    process.wait()
    assert lines == ["Привет", "Мир"]
