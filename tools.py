import csv
import inspect
import io
import json
import subprocess
import sys
from contextvars import ContextVar
from pathlib import Path

import pandas as pd


WORKSPACE = ContextVar("workspace")
MAX_BYTES = 2_000_000
PROTECTED = {"demo.csv", "data.csv"}


def resolve_path(path: str) -> Path:
    root = WORKSPACE.get().resolve()
    relative = Path(path)
    target = (root / relative).resolve()

    if relative.is_absolute() or not target.is_relative_to(root):
        raise ValueError(
            "Доступ дозволено лише до файлів цієї сесії."
        )

    return target


def load_csv_bytes(raw: bytes) -> pd.DataFrame:
    if len(raw) > MAX_BYTES:
        raise ValueError("Максимальний розмір CSV — 2 МБ.")

    text = raw.decode("utf-8-sig")

    try:
        separator = csv.Sniffer().sniff(
            text[:4096],
            delimiters=",;\t"
        ).delimiter
    except csv.Error:
        separator = ","

    frame = pd.read_csv(
        io.StringIO(text),
        sep=separator,
        nrows=10001
    )

    if len(frame) > 10000 or len(frame.columns) > 50:
        raise ValueError(
            "Дозволено до 10 000 рядків і 50 стовпців."
        )

    return frame


def load_csv(path: str) -> pd.DataFrame:
    target = resolve_path(path)

    if target.suffix.lower() != ".csv":
        raise ValueError("Потрібен файл із розширенням .csv.")

    return load_csv_bytes(target.read_bytes())


def write_text(
    path: str,
    text: str,
    overwrite: bool = False
) -> str:
    target = resolve_path(path)
    root = WORKSPACE.get().resolve()

    if target.parent != root or target.name in PROTECTED:
        raise ValueError(
            "Зберігай результат в окремому файлі у корені сесії."
        )

    if target.exists() and not overwrite:
        raise ValueError(
            "Такий файл уже існує. Обери нове ім'я результату."
        )

    if target.suffix.lower() not in {
        ".csv", ".md", ".txt", ".json"
    }:
        raise ValueError(
            "Дозволено записувати лише CSV, MD, TXT та JSON."
        )

    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Результат перевищує 2 МБ.")

    if not target.exists() and len(list(root.iterdir())) >= 20:
        raise ValueError("У сесії вже є 20 файлів.")

    target.write_text(text, encoding="utf-8")
    return target.name


def terminal(command: str) -> dict:
    """Виконує одну з трьох команд: pwd, ls, python --version.
    Інші команди заборонені.
    """
    commands = {
        "pwd": [
            sys.executable,
            "-c",
            "import os; print(os.getcwd())"
        ],
        "ls": [
            sys.executable,
            "-X",
            "utf8",
            "-c",
            (
                "from pathlib import Path; "
                "print('\\n'.join("
                "sorted(p.name for p in Path('.').iterdir())))"
            )
        ],
        "python --version": [
            sys.executable,
            "--version"
        ],
    }

    if command.strip() not in commands:
        raise ValueError(
            "Дозволені команди: pwd, ls, python --version."
        )

    result = subprocess.run(
        commands[command.strip()],
        cwd=WORKSPACE.get(),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
    )

    return {
        "stdout": result.stdout[:4000],
        "stderr": result.stderr[:4000],
        "returncode": result.returncode
    }


def list_directory(path: str = ".") -> list:
    """Повертає список файлів та папок сесії.
    Для кореня передай path='.'.
    """
    return [
        {
            "name": p.name,
            "type": "directory" if p.is_dir() else "file"
        }
        for p in sorted(resolve_path(path).iterdir())
    ]


def read_file(path: str) -> dict:
    """Читає текстовий файл сесії.
    Повертає до 6000 символів і ознаку скорочення.
    """
    target = resolve_path(path)

    if target.stat().st_size > MAX_BYTES:
        raise ValueError("Файл перевищує 2 МБ.")

    text = target.read_text(encoding="utf-8-sig")

    return {
        "text": text[:6000],
        "truncated": len(text) > 6000
    }


def edit_file(
    path: str,
    old_str: str,
    new_str: str
) -> dict:
    """Замінює один точний збіг old_str на new_str.
    Оригінали demo.csv та data.csv захищені.
    """
    if not old_str:
        raise ValueError("old_str не може бути порожнім.")

    text = resolve_path(path).read_text(
        encoding="utf-8-sig"
    )

    if text.count(old_str) != 1:
        raise ValueError(
            "old_str має зустрічатися рівно один раз."
        )

    name = write_text(
        path,
        text.replace(old_str, new_str, 1),
        overwrite=True
    )

    return {
        "saved_file": name,
        "replacements": 1
    }


def profile_csv(path: str) -> dict:
    """Аналізує CSV: рядки, стовпці, типи, пропуски,
    повні дублікати, числову статистику, перші 5 рядків.
    """
    frame = load_csv(path)
    numeric = frame.select_dtypes(include="number")

    return {
        "rows": len(frame),
        "columns": len(frame.columns),

        "dtypes": {
            str(k): str(v)
            for k, v in frame.dtypes.items()
        },

        "missing": {
            str(k): int(v)
            for k, v in frame.isna().sum().items()
        },

        "duplicate_rows": int(
            frame.duplicated().sum()
        ),

        "numeric_statistics": (
            json.loads(
                numeric.describe().round(3).to_json()
            )
            if not numeric.empty
            else {}
        ),

        "preview": json.loads(
            frame.head(5).to_json(orient="records")
        ),
    }


def clean_csv(
    path: str,
    output_path: str = "cleaned.csv",
    drop_duplicates: bool = True,
    missing: str = "keep"
) -> dict:
    """Зберігає очищену копію CSV.
    missing: keep — залишити пропуски;
    drop_rows — видалити рядки з пропусками;
    fill — медіана для чисел, Невідомо для тексту.
    Повні дублікати видаляються першими,
    якщо drop_duplicates=true.
    """
    if missing not in {"keep", "drop_rows", "fill"}:
        raise ValueError(
            "missing: keep, drop_rows або fill."
        )

    if Path(output_path).suffix.lower() != ".csv":
        raise ValueError(
            "output_path має закінчуватися на .csv."
        )

    frame = load_csv(path)
    rows_before = len(frame)
    missing_before = int(
        frame.isna().sum().sum()
    )

    if drop_duplicates:
        frame = frame.drop_duplicates().copy()

    removed_duplicates = rows_before - len(frame)

    if missing == "drop_rows":
        frame = frame.dropna().copy()

    elif missing == "fill":
        for column in frame.columns:
            if pd.api.types.is_numeric_dtype(
                frame[column]
            ):
                median = frame[column].median()

                if pd.notna(median):
                    frame[column] = (
                        frame[column].fillna(median)
                    )
            else:
                frame[column] = (
                    frame[column].fillna("Невідомо")
                )

    name = write_text(
        output_path,
        frame.to_csv(index=False)
    )

    return {
        "saved_file": name,
        "rows_before": rows_before,
        "rows_after": len(frame),
        "removed_duplicates": removed_duplicates,
        "missing_strategy": missing,
        "missing_before": missing_before,
        "missing_after": int(
            frame.isna().sum().sum()
        ),
    }


def aggregate_csv(
    path: str,
    group_column: str,
    value_column: str,
    operation: str = "sum",
    output_path: str = "summary.csv"
) -> dict:
    """Групує CSV за group_column і обчислює sum, mean,
    min, max або count для value_column.
    count рахує непорожні значення.
    Зберігає окремий CSV.
    """
    if operation not in {
        "sum", "mean", "min", "max", "count"
    }:
        raise ValueError(
            "operation: sum, mean, min, max або count."
        )

    if Path(output_path).suffix.lower() != ".csv":
        raise ValueError(
            "output_path має закінчуватися на .csv."
        )

    frame = load_csv(path)

    if (
        group_column not in frame
        or value_column not in frame
    ):
        raise ValueError(
            "Перевір назви стовпців через profile_csv."
        )

    if (
        operation != "count"
        and not pd.api.types.is_numeric_dtype(
            frame[value_column]
        )
    ):
        raise ValueError(
            "Для цієї операції потрібен числовий стовпець."
        )

    groups = frame.groupby(
        group_column,
        dropna=False
    )[value_column]

    values = (
        groups.sum(min_count=1)
        if operation == "sum"
        else groups.agg(operation)
    )

    result = values.rename(
        f"{operation}_{value_column}"
    ).reset_index()

    name = write_text(
        output_path,
        result.to_csv(index=False)
    )

    return {
        "saved_file": name,
        "groups": len(result),
        "preview": json.loads(
            result.head(10).to_json(orient="records")
        )
    }


def save_report(path: str, text: str) -> dict:
    """Зберігає текстовий висновок про дані у файл .md або .txt.
    Числа мають спиратися на результати інструментів.
    """
    if Path(path).suffix.lower() not in {".md", ".txt"}:
        raise ValueError(
            "Для висновку використовуй .md або .txt."
        )

    return {
        "saved_file": write_text(path, text)
    }


FUNCTIONS = {
    f.__name__: f
    for f in (
        terminal,
        list_directory,
        read_file,
        edit_file,
        profile_csv,
        clean_csv,
        aggregate_csv,
        save_report,
    )
}


def tool_schemas() -> list:
    types = {
        str: "string",
        bool: "boolean"
    }

    schemas = []

    for name, function in FUNCTIONS.items():
        parameters = inspect.signature(
            function
        ).parameters

        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": inspect.getdoc(function),
                "parameters": {
                    "type": "object",

                    "properties": {
                        n: {
                            "type": types[p.annotation]
                        }
                        for n, p in parameters.items()
                    },

                    "required": [
                        n
                        for n, p in parameters.items()
                        if p.default is inspect.Parameter.empty
                    ],

                    "additionalProperties": False,
                },
            }
        })

    return schemas


def execute_tool(
    name: str,
    arguments: dict,
    workspace: Path
) -> dict:
    token = WORKSPACE.set(workspace)

    try:
        function = FUNCTIONS[name]
        signature = inspect.signature(function)
        bound = signature.bind(**arguments)

        for key, value in bound.arguments.items():
            expected = signature.parameters[key].annotation

            if type(value) is not expected:
                raise ValueError(
                    f"Неправильний тип параметра {key}."
                )

        return {
            "ok": True,
            "data": function(**arguments)
        }

    except Exception as error:
        return {
            "ok": False,
            "error": str(error)
        }

    finally:
        WORKSPACE.reset(token)