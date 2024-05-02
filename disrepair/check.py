import requests
from packaging.version import InvalidVersion, Version
from pypi_simple import NoSuchProjectError, PyPISimple, UnsupportedContentTypeError, UnsupportedRepoVersionError
from rich import box, progress
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .options import Options
from .reqfile import Line, ParseStatus, ReqFile, UpdateStatus


class CheckFailed(Exception):
    pass


class Disrepair:
    requirements_files: list[ReqFile] = []
    updates: list[Line] = []
    unpinned: list[Line] = []
    up2date: list[Line] = []
    errors: list[Line] = []
    unsupported: list[Line] = []

    def __init__(self, opt: Options):
        self.console = Console()
        opt.json_repo = opt.json_repo.rstrip('/')
        opt.simple_repo = opt.simple_repo.rstrip('/')
        self.opt = opt

    def get_pypi_version(self, name: str) -> tuple[str | None, str | None]:
        try:
            r = requests.get(f"{self.opt.json_repo}/{name}/json", timeout=3)
        except requests.Timeout:
            raise CheckFailed("Timeout exceeded when connecting to PyPI")
        except requests.ConnectionError:
            raise CheckFailed("Unable to connect to PyPI")

        if r.status_code == 404:
            return None, None

        if not r.ok:
            raise CheckFailed(f"PyPI return code {r.status_code}")

        data = r.json()
        try:
            ver = data["info"]["version"]
        except KeyError:
            raise CheckFailed("PyPI returned a malformed response")

        if 'info' in data:
            if 'project_urls' in data['info']:
                if data['info']['project_urls']:
                    if 'Changelog' in data['info']['project_urls']:
                        if data['info']['project_urls']['Changelog']:
                            return ver, data['info']['project_urls']['Changelog']

                    if 'Changes' in data['info']['project_urls']:
                        if data['info']['project_urls']['Changes']:
                            return ver, data['info']['project_urls']['Changes']

            if 'docs_url' in data['info']:
                if data['info']['docs_url']:
                    return ver, data['info']['docs_url']

            if 'project_url' in data['info']:
                if data['info']['project_url']:
                    return ver, data['info']['project_url']

            if 'home_page' in data['info']:
                if data['info']['home_page']:
                    return ver, data['info']['home_page']

            if 'package_url' in data['info']:
                if data['info']['package_url']:
                    return ver, data['info']['package_url']

        return ver, None

    def get_pypi_simple_version(self, name: str) -> tuple[str | None, str | None]:
        with PyPISimple(endpoint=self.opt.simple_repo) as client:
            try:
                page = client.get_project_page(name, timeout=5)
            except requests.RequestException:
                raise CheckFailed("Connection error")
            except UnsupportedRepoVersionError:
                raise CheckFailed("Unsupported repo version")
            except UnsupportedContentTypeError:
                raise CheckFailed("Unsupported content type")
            except NoSuchProjectError:
                raise CheckFailed("Package not found")
            except Exception as exc:
                raise CheckFailed(f"Unexpected error: {exc}")

            if page is None:
                raise CheckFailed("Package not found")

            if not page.packages:
                raise CheckFailed("Package not found")

            # There is not a guarantee that versions are listed in order.
            # We must thus check every version and pick the latest stable version.

            chosen_version = None
            for pkg in page.packages:
                if pkg.version is None:
                    continue
                try:
                    pkg_version_obj = Version(pkg.version)
                except InvalidVersion:
                    continue

                if (
                    not pkg_version_obj.is_devrelease
                    and not pkg_version_obj.is_postrelease
                    and not pkg_version_obj.is_prerelease
                ):

                    if chosen_version is None:
                        chosen_version = pkg.version
                        chosen_version_obj = pkg_version_obj
                    else:
                        if pkg_version_obj > chosen_version_obj:
                            chosen_version = pkg.version
                            chosen_version_obj = pkg_version_obj

            if chosen_version is None:
                raise CheckFailed("Could not find a suitable version")

            # The simple api offers no url :(
            return chosen_version, None

    def get_version(self, name: str) -> tuple[str | None, str | None]:
        latest = None
        if not self.opt.simple_only:
            try:
                latest, url = self.get_pypi_version(name)
            except CheckFailed:
                if self.opt.json_only:
                    raise

        if not self.opt.json_only:
            if latest is None:
                latest, url = self.get_pypi_simple_version(name)

        if latest is None:
            raise CheckFailed("Package not found")

        return latest, url

    def _parse_file(self, filename: str) -> None:
        rf = ReqFile(filename)
        self.requirements_files.append(rf)

        for fp in rf.other_files:
            self._parse_file(fp)

    def _fetch_metadata(self) -> None:
        lines: list[Line] = []
        for reqfile in self.requirements_files:
            lines.extend(reqfile.lines)

        with progress.Progress(
            progress.SpinnerColumn(),
            progress.TextColumn("[progress.description]{task.description}"),
            progress.BarColumn(),
            progress.TaskProgressColumn(),
            progress.MofNCompleteColumn(),
            console=self.console,
            transient=True,
        ) as status:
            task = status.add_task("[bold]Checking", total=len(lines))
            for line in lines:
                if line.status == ParseStatus.requirement:
                    if line.pkgname:
                        try:
                            line.latest, line.url = self.get_version(line.pkgname)
                        except CheckFailed as ex:
                            line.error = str(ex)
                            self.errors.append(line)
                        else:
                            if line.spec is None:
                                line.update = UpdateStatus.unpinned
                                self.unpinned.append(line)
                            else:
                                if line.latest:
                                    ver_latest = Version(line.latest)
                                    ver_spec = Version(line.spec)
                                    if ver_latest > ver_spec:
                                        line.update = UpdateStatus.behind
                                        self.updates.append(line)

                                    elif ver_latest == ver_spec:
                                        line.update = UpdateStatus.ok
                                        self.up2date.append(line)

                                    elif ver_latest < ver_spec:
                                        line.error = (
                                            "Specified version "
                                            f"({line.spec}) is greater than the "
                                            f"latest published version ({line.latest})"
                                        )
                                        self.errors.append(line)

                elif line.status == ParseStatus.error:
                    self.errors.append(line)
                elif line.status == ParseStatus.unsupported:
                    self.unsupported.append(line)

                status.update(task, advance=1)

    def _print_reqs(self) -> None:
        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Package", no_wrap=True)
        if len(self.requirements_files) > 1:
            table.add_column("Location", no_wrap=True)
        table.add_column("Spec", no_wrap=True)
        table.add_column("Latest", no_wrap=True)
        if self.opt.info:
            table.add_column("URL")

        if self.opt.verbose:
            for line in self.up2date:
                row = [line.pkgname]
                if len(self.requirements_files) > 1:
                    row.append(line.location)
                row.extend([line.spec, '✅ Up to date'])
                if self.opt.info:
                    row.append(line.url)
                table.add_row(*row)

        for line in self.updates:
            row = [line.pkgname]
            if len(self.requirements_files) > 1:
                row.append(line.location)
            row.extend([line.spec, line.latest])
            if self.opt.info:
                row.append(line.url)
            table.add_row(*row)

        if self.opt.unpinned:
            for line in self.unpinned:
                row = [line.pkgname]
                if len(self.requirements_files) > 1:
                    row.append(line.location)
                row.extend(['⚠️  Unpinned', line.latest])
                if self.opt.info:
                    row.append(line.url)
                table.add_row(*row)

        if table.rows:
            self.console.print(table)

    def _print_errors_unsupported(self) -> None:
        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Line")
        table.add_column("Package")
        table.add_column("Error")

        for line in self.errors:
            loc = str(line.lineno)
            if len(self.requirements_files) > 1:
                loc = line.location
            table.add_row(loc, line.pkgname or '', line.error)

        if self.opt.verbose:
            for line in self.unsupported:
                loc = str(line.lineno)
                if len(self.requirements_files) > 1:
                    loc = line.location
                table.add_row(loc, line.pkgname or '', line.error)

        if table.rows:
            self.console.print(table)

    def cmd_update(self, filename: str) -> None:
        self._parse_file(filename)
        self._fetch_metadata()

        printed = False
        multiple = len(self.requirements_files) > 1

        for reqfile in self.requirements_files:
            num_updated = 0

            for line in reqfile.lines:
                if line.status == ParseStatus.requirement:
                    if line.update == UpdateStatus.behind or line.update == UpdateStatus.unpinned:
                        if self.opt.auto_update:
                            do_update = True
                        else:
                            if printed:
                                self.console.print('')
                            printed = True
                            if multiple:
                                self.console.print(f'[bold]{line.pkgname}[/bold] {reqfile.filename}')
                            else:
                                self.console.print(f'[bold]{line.pkgname}')
                            if self.opt.info:
                                if line.url is not None:
                                    self.console.print(line.url)
                            self.console.print(f'Current: {line.spec or "Unpinned"}')
                            self.console.print(f'Latest: {line.latest}')
                            do_update = Confirm.ask("Do you want to update?", default=True)

                        if do_update:
                            num_updated += 1
                            line.line = f'{line.pkgname}=={line.latest}'

        for reqfile in self.requirements_files:
            if num_updated:
                with open(reqfile.filepath, mode='w') as fp:
                    for line in reqfile.lines:
                        if line.line is not None:
                            fp.write(line.line)
                            if not line.line.endswith('\n'):
                                fp.write('\n')

                if self.opt.auto_update or self.errors:
                    self.console.print(
                        f"{reqfile.filename}: {num_updated} package{'s' if num_updated > 1 else ''} updated"
                    )

        self._print_errors_unsupported()

    def cmd_check(self, filename: str) -> None:
        self._parse_file(filename)
        self._fetch_metadata()
        self._print_reqs()
        self._print_errors_unsupported()
