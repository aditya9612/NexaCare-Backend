from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.core.logger import logger

env = Environment(loader=FileSystemLoader("app/templates"))


async def generate_report(report_type: str, data: dict, output_path: str) -> str:
    template = env.get_template("report_template.html")
    html = template.render(report_type=report_type, **data)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("Report generated: %s", output_path)
    return str(path)
