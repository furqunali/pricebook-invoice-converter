"""Command-line entry point (console script: ``invoice2pdi``).

Windows Task Scheduler calls ``invoice2pdi batch`` (and ``review-run``) twice a
day on the always-on server. All data paths come from settings.yaml — point them
at your own data folder before scheduling. ``convert`` is for manual/adhoc
testing of a single file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .batch import run_batch
from .config import Settings
from .pipeline import convert_file
from .review import run_review

app = typer.Typer(add_completion=False, help="Pricebook/PDI invoice converter.")


def _print_run(result) -> None:
    typer.echo(f"{result.batch_id}: in_batch={len(result.in_batch)} "
               f"review={len(result.review)}")
    if result.has_output:
        typer.echo(f"  dropzone -> {result.dropzone_file}")
    else:
        typer.echo("  (nothing passed; no dropzone file written)")
    typer.echo(f"  manifest -> {result.manifest_file}")


@app.command()
def batch(config: Optional[Path] = typer.Option(None, help="Path to settings.yaml")):
    """Daily batch run (produces B-n). Scheduled 2x/day on the server."""
    settings = Settings.load(config) if config else Settings.load()
    _print_run(run_batch(settings=settings))


@app.command(name="review-run")
def review_run(config: Optional[Path] = typer.Option(None, help="Path to settings.yaml")):
    """Re-run reviewer-approved items from reprocess/ (produces R-n)."""
    settings = Settings.load(config) if config else Settings.load()
    _print_run(run_review(settings=settings))


@app.command()
def report(
    period: Optional[str] = typer.Option(None, help="Period label (default: this month, YYYY-MM)"),
    out: Optional[Path] = typer.Option(None, help="Output folder (default: reports dir)"),
    config: Optional[Path] = typer.Option(None, help="Path to settings.yaml"),
):
    """Build the store-wise purchase + reconciliation report (PDF + Excel +
    Power BI dataset) from the converter output. Subscription/offline — no API."""
    from .report_render import build_reports
    settings = Settings.load(config) if config else Settings.load()
    r = build_reports(settings=settings, out_dir=out, period=period)
    typer.echo(f"invoices={r['invoices']}  total=${r['total']:,.2f}  "
               f"recon={r['recon_status']}")
    typer.echo(f"  excel   -> {r['excel']}")
    typer.echo(f"  pdf     -> {r['pdf']}")
    for p in r["powerbi"]:
        typer.echo(f"  powerbi -> {p}")


@app.command()
def convert(
    path: Path = typer.Argument(..., help="Invoice file to convert"),
    site: Optional[str] = typer.Option(None, help="Force a site id"),
    vendor: Optional[str] = typer.Option(None, help="Force a vendor id"),
    config: Optional[Path] = typer.Option(None, help="Path to settings.yaml"),
):
    """Convert ONE invoice (manual/testing). Prints the PDI records or the reason."""
    settings = Settings.load(config) if config else Settings.load()
    res = convert_file(path, settings=settings, site_override=site, vendor_override=vendor)
    if res.ok:
        typer.echo(res.csv_text, nl=False)
    else:
        typer.echo(f"REVIEW ({path.name}):", err=True)
        typer.echo(res.reason_text(), err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
