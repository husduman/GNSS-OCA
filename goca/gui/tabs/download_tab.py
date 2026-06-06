import os
import re
import threading
import queue
import tkinter as tk
import ssl
import socket
import time
import requests

from tkinter import ttk, filedialog
from tkcalendar import Calendar
from datetime import date, datetime
from urllib.request import Request, urlopen, urlretrieve
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from pathlib import Path
from ftplib import FTP, FTP_TLS

from goca.data_centers import DATA_CENTERS
from goca.archive_urls import ARCHIVE_URLS


class ImplicitFTP_TLS(FTP_TLS):
    """FTP_TLS subclass for implicit FTPS servers, e.g. ftps://host:990.

    Standard ftplib.FTP_TLS starts TLS after an FTP control connection is
    opened. Implicit FTPS requires TLS immediately after TCP connect, before
    the welcome message is read.
    """

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if host:
            self.host = host
        if port:
            self.port = port
        if timeout != -999:
            self.timeout = timeout

        raw_sock = socket.create_connection(
            (self.host, self.port),
            self.timeout,
            source_address
        )

        self.sock = self.context.wrap_socket(
            raw_sock,
            server_hostname=self.host
        )

        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


class DownloadTab:
    """
    Download Products Tab
    """

    def __init__(self, parent_frame):
        self.parent = parent_frame
        self._cancel_requested = False
        self._download_thread = None
        self._log_queue = queue.Queue()        

        # Cache archive directory listings. This avoids checking hundreds of
        # candidate URLs one by one for the same date/archive folder.
        self._archive_listing_cache = {}
        self._active_response = None
        self._active_session = None

        self._build_ui()

    def _build_ui(self):

        frame = self.parent

        # ==========================================
        # LEFT PANEL
        # ==========================================
        self.left_panel = ttk.LabelFrame(
            frame,
            text="Operations",
            padding=5
        )
        self.left_panel.configure(width=350)
        self.left_panel.pack(side="left", fill="y")
        self.left_panel.pack_propagate(False)

        # ==========================================
        # Analysis Center
        # ==========================================
        center_frame = ttk.LabelFrame(
            self.left_panel,
            text="Analysis Center",
            padding=5
        )
        center_frame.pack(padx=5, pady=5, fill="x")

        self.analysis_center_var = tk.StringVar()

        self.analysis_center_combo = ttk.Combobox(
            center_frame,
            textvariable=self.analysis_center_var,
            state="readonly",
            values=sorted(DATA_CENTERS.keys())
        )

        self.analysis_center_combo.pack(fill="x", padx=5, pady=2)

        # Default selection
        self.analysis_center_combo.current(0)


        # ==========================================
        # Product Type
        # ==========================================
        product_frame = ttk.LabelFrame(
            self.left_panel,
            text="Product Type",
            padding=5
        )
        product_frame.pack(padx=5, pady=5, fill="x")

        self.final_var = tk.IntVar(value=1)
        self.rapid_var = tk.IntVar(value=0)
        self.ultrarapid_var = tk.IntVar(value=0)

        tk.Checkbutton(
            product_frame,
            text="Final",
            variable=self.final_var
        ).grid(row=0, column=0, sticky="w", padx=5)

        tk.Checkbutton(
            product_frame,
            text="Rapid",
            variable=self.rapid_var
        ).grid(row=0, column=1, sticky="w", padx=15)

        tk.Checkbutton(
            product_frame,
            text="Ultra-rapid",
            variable=self.ultrarapid_var
        ).grid(row=0, column=2, sticky="w", padx=15)


        # ==========================================
        # Product File Type
        # ==========================================
        filetype_frame = ttk.LabelFrame(
            self.left_panel,
            text="Product File Type",
            padding=5
        )
        filetype_frame.pack(padx=5, pady=5, fill="x")

        self.sp3_var = tk.IntVar(value=1)
        self.clk_var = tk.IntVar(value=1)
        self.bia_var = tk.IntVar(value=1)
        self.obx_var = tk.IntVar(value=1)
        self.erp_var = tk.IntVar(value=1)

        tk.Checkbutton(
            filetype_frame,
            text="SP3 (Precise Satellite Ephemerides)",
            variable=self.sp3_var
        ).pack(anchor="w", pady=1)

        tk.Checkbutton(
            filetype_frame,
            text="CLK (Precise Satellite Clock Information)",
            variable=self.clk_var
        ).pack(anchor="w", pady=1)

        tk.Checkbutton(
            filetype_frame,
            text="BIA (Observable-specific Signal Bias)",
            variable=self.bia_var
        ).pack(anchor="w", pady=1)

        tk.Checkbutton(
            filetype_frame,
            text="OBX (Attitude Quaternions of Satellites)",
            variable=self.obx_var
        ).pack(anchor="w", pady=1)

        tk.Checkbutton(
            filetype_frame,
            text="ERP (Earth Rotation/Orientation Parameter)",
            variable=self.erp_var
        ).pack(anchor="w", pady=1)


        # ==========================================
        # Date Range
        # ==========================================
        date_frame = ttk.LabelFrame(
            self.left_panel,
            text="Date Range",
            padding=5
        )
        date_frame.pack(padx=5, pady=5, fill="x")


        def _parse_date_from_entry(entry_widget):
            try:
                return datetime.strptime(entry_widget.get().strip(), "%Y-%m-%d").date()
            except Exception:
                return date.today()


        def _set_entry_date(entry_widget, value_date):
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, value_date.strftime("%Y-%m-%d"))


        def _validate_date_range(changed_entry=None):
            from_date = _parse_date_from_entry(self.date_from_entry)
            to_date = _parse_date_from_entry(self.date_to_entry)

            if to_date < from_date:
                _set_entry_date(self.date_to_entry, from_date)


        def attach_inline_calendar(entry_widget, role="from"):
            # Eğer takvim açıksa kapat
            if hasattr(self, "_calendar_popup") and self._calendar_popup is not None:
                self._calendar_popup.destroy()
                self._calendar_popup = None

            self._calendar_popup = tk.Frame(
                date_frame,
                relief="solid",
                borderwidth=1
            )
            self._calendar_popup.grid(
                row=2,
                column=0,
                columnspan=3,
                padx=5,
                pady=5,
                sticky="w"
            )

            selected_date = _parse_date_from_entry(entry_widget)

            cal_kwargs = dict(
                master=self._calendar_popup,
                selectmode="day",
                date_pattern="yyyy-mm-dd",
                year=selected_date.year,
                month=selected_date.month,
                day=selected_date.day
            )

            # To takviminde From'dan önceki tarihleri disable et
            if role == "to":
                cal_kwargs["mindate"] = _parse_date_from_entry(self.date_from_entry)

            cal = Calendar(**cal_kwargs)
            cal.pack(padx=5, pady=5)

            def set_date(event=None):
                chosen_date = cal.selection_get()

                if role == "to":
                    from_date = _parse_date_from_entry(self.date_from_entry)
                    if chosen_date < from_date:
                        chosen_date = from_date

                _set_entry_date(entry_widget, chosen_date)

                if role == "from":
                    _validate_date_range(changed_entry=self.date_from_entry)

                if self._calendar_popup is not None:
                    self._calendar_popup.destroy()
                    self._calendar_popup = None

            # Çift tıklama ile seçim
            cal.bind("<Double-1>", set_date)

            ttk.Button(
                self._calendar_popup,
                text="Select",
                command=set_date
            ).pack(pady=(0, 5))


        today = date.today().strftime("%Y-%m-%d")

        tk.Label(
            date_frame,
            text="From"
        ).grid(
            row=0,
            column=0,
            sticky="w",
            padx=5,
            pady=3
        )

        self.date_from_entry = ttk.Entry(date_frame, width=14)
        self.date_from_entry.insert(0, today)
        self.date_from_entry.grid(
            row=0,
            column=1,
            sticky="w",
            padx=5,
            pady=3
        )

        ttk.Button(
            date_frame,
            text="▼",
            width=3,
            command=lambda: attach_inline_calendar(self.date_from_entry, role="from")
        ).grid(
            row=0,
            column=2,
            padx=3
        )


        tk.Label(
            date_frame,
            text="To"
        ).grid(
            row=1,
            column=0,
            sticky="w",
            padx=5,
            pady=3
        )

        self.date_to_entry = ttk.Entry(date_frame, width=14)
        self.date_to_entry.insert(0, today)
        self.date_to_entry.grid(
            row=1,
            column=1,
            sticky="w",
            padx=5,
            pady=3
        )

        ttk.Button(
            date_frame,
            text="▼",
            width=3,
            command=lambda: attach_inline_calendar(self.date_to_entry, role="to")
        ).grid(
            row=1,
            column=2,
            padx=3
        )

        self._calendar_popup = None

        # ==========================================
        # Download Folder
        # ==========================================
        download_folder_frame = ttk.LabelFrame(
            self.left_panel,
            text="Download Folder",
            padding=5
        )
        download_folder_frame.pack(padx=5, pady=5, fill="x")

        self.download_folder_var = tk.StringVar(value=os.getcwd())

        self.download_folder_entry = ttk.Entry(
            download_folder_frame,
            textvariable=self.download_folder_var
        )
        self.download_folder_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(5, 5),
            pady=3
        )

        self.download_folder_browse = ttk.Button(
            download_folder_frame,
            text="...",
            width=3,
            command=self.select_download_folder
        )
        self.download_folder_browse.pack(
            side="left",
            padx=(0, 5),
            pady=3
        )


        # ---------------------------------------------------
        # BUTTONS
        # ---------------------------------------------------
        btn_bottom = tk.Frame(self.left_panel)
        btn_bottom.pack(side="bottom", padx=5, pady=5, fill="x")

        # üst satır
        top_row = tk.Frame(btn_bottom)
        top_row.pack(fill="x", pady=(0, 5))

        clear_info_btn = tk.Button(
            top_row,
            text="Clear Info",
            padx=5,
            pady=8,
            cursor="hand2",
            command=self.clear_info
        )
        clear_info_btn.pack(side="left", expand=True, fill="x", padx=(0, 3))

        kill_btn = tk.Button(
            top_row,
            text="Kill Process",
            padx=5,
            pady=8,
            cursor="hand2",
            command=self.kill_process
        )
        kill_btn.pack(side="left", expand=True, fill="x", padx=(3, 0))

        # alt satır
        download_btn = tk.Button(
            btn_bottom,
            text="Download",
            font=("Helvetica", 12, "bold"),
            padx=5,
            pady=10,
            cursor="hand2",
            command=self.download_files
        )
        download_btn.pack(fill="x")

        
        # ==========================================
        # RIGHT PANEL - INFO LOG
        # ==========================================
        self.main_area = ttk.LabelFrame(
            frame,
            text="Information",
            padding=5
        )
        self.main_area.pack(
            side="left",
            fill="both",
            expand=True
        )

        self.info_text = tk.Text(
            self.main_area,
            wrap="word",
            bg="white",
            state="disabled"
        )

        self.info_text.pack(
            side="left",
            fill="both",
            expand=True
        )

        scrollbar = ttk.Scrollbar(
            self.main_area,
            orient="vertical",
            command=self.info_text.yview
        )
        scrollbar.pack(side="right", fill="y")

        self.info_text.configure(
            yscrollcommand=scrollbar.set
        )


    def _parse_date_entry(self, entry_widget):
        """Parse YYYY-MM-DD date from an Entry widget."""
        return datetime.strptime(entry_widget.get().strip(), "%Y-%m-%d").date()


    def _selected_product_types(self):
        selected = []
        if self.final_var.get() == 1:
            selected.append("Final")
        if self.rapid_var.get() == 1:
            selected.append("Rapid")
        if self.ultrarapid_var.get() == 1:
            selected.append("Ultra-rapid")
        return selected


    def _selected_file_types(self):
        selected = []
        if self.sp3_var.get() == 1:
            selected.append("SP3")
        if self.clk_var.get() == 1:
            selected.append("CLK")
        if self.bia_var.get() == 1:
            selected.append("BIA")
        if self.obx_var.get() == 1:
            selected.append("OBX")
        if self.erp_var.get() == 1:
            selected.append("ERP")
        return selected


    def _date_range(self, start_date, end_date):
        """Yield dates from start_date to end_date, inclusive."""
        current = start_date
        while current <= end_date:
            yield current
            current = current.fromordinal(current.toordinal() + 1)


    def download_files(self):
        if self._download_thread is not None and self._download_thread.is_alive():
            self.log_message("WARNING: Download process is already running.")
            return

        self._cancel_requested = False

        self._download_thread = threading.Thread(
            target=self._download_files_worker,
            daemon=True
        )
        self._download_thread.start()

        self._poll_log_queue()

    def _download_files_worker(self):
        try:
            # --------------------------------------------------
            center = self.analysis_center_var.get().strip()
            center_cfg = DATA_CENTERS.get(center, {})

            product_types = self._selected_product_types()
            file_types = self._selected_file_types()
            download_folder = self.download_folder_var.get().strip()

            # --------------------------------------------------
            try:
                date_from = self._parse_date_entry(self.date_from_entry)
                date_to = self._parse_date_entry(self.date_to_entry)
            except Exception:
                self._queue_log("ERROR: Date format must be YYYY-MM-DD.")
                return

            if date_to < date_from:
                self._queue_log("ERROR: End date cannot be earlier than start date.")
                return

            # --------------------------------------------------
            if not center_cfg:
                self._queue_log(f"ERROR: Unknown analysis center: {center}")
                return

            if not product_types:
                self._queue_log("WARNING: No product type selected.")
                return

            if not file_types:
                self._queue_log("WARNING: No product file type selected.")
                return

            if not download_folder:
                self._queue_log("WARNING: Download folder is empty.")
                return

            archive_names = center_cfg.get("archive", [])

            if not archive_names:
                self._queue_log(f"ERROR: No archive defined for {center}.")
                return

            # --------------------------------------------------
            self._queue_log("=" * 72)
            self._queue_log("Download started.")
            self._queue_log(f"Analysis Center : {center}")
            self._queue_log(f"Archive Order   : {', '.join(archive_names)}")
            self._queue_log(f"Product Type(s) : {', '.join(product_types)}")
            self._queue_log(f"File Type(s)    : {', '.join(file_types)}")
            self._queue_log(f"Date Range      : {date_from} -> {date_to}")
            self._queue_log(f"Download Folder : {download_folder}")
            self._queue_log("Rule            : Try v3 first. If not found and v2=True, try v2.")
            self._queue_log("Order           : Date -> Product Type -> File Type")
            self._queue_log("=" * 72)

            found_count = 0
            missing_count = 0
            downloaded_count = 0
            failed_count = 0

            # ==================================================
            for dt in self._date_range(date_from, date_to):

                if self._cancel_requested:
                    self._queue_log("Download process cancelled by user.")
                    return

                self._queue_log("")
                self._queue_log("=" * 72)
                self._queue_log(f"DATE: {dt}")
                self._queue_log("=" * 72)

                for product_type in product_types:

                    if self._cancel_requested:
                        self._queue_log("Download process cancelled by user.")
                        return

                    product_cfg = center_cfg.get(product_type)

                    if not product_cfg:
                        self._queue_log(
                            f"SKIP: {center} has no {product_type} product."
                        )
                        continue

                    prefix = product_cfg.get("prefix", "")
                    products = product_cfg.get("products", {})

                    if not prefix:
                        self._queue_log(
                            f"SKIP: Missing prefix for {center} / {product_type}."
                        )
                        continue

                    for file_type in file_types:

                        if self._cancel_requested:
                            self._queue_log("Download process cancelled by user.")
                            return

                        file_cfg = products.get(file_type)

                        if not file_cfg:
                            self._queue_log(
                                f"SKIP: {file_type} not available for "
                                f"{center} / {product_type}."
                            )
                            continue

                        allow_v2 = bool(file_cfg.get("v2", False))

                        self._queue_log("-" * 72)
                        self._queue_log(
                            f"SEARCH: {product_type} | {file_type} | "
                            f"prefix={prefix} | v2={allow_v2}"
                        )

                        # ------------------------------------------
                        found = self._find_best_file_url(
                            archive_names=archive_names,
                            prefix=prefix,
                            dt=dt,
                            file_type=file_type,
                            allow_v2=allow_v2
                        )

                        if not found:
                            missing_count += 1
                            self._queue_log(
                                f"NOT FOUND: {dt} | {product_type} | {file_type}"
                            )
                            continue

                        found_count += 1

                        self._queue_log(
                            f"FOUND: {found['url']}"
                        )
                        self._queue_log(
                            f"INFO : archive={found.get('archive', '')} | "
                            f"version={found.get('version', '')} | "
                            f"length={found.get('length', '')} | "
                            f"sampling={found.get('sampling', '')}"
                        )

                        # ------------------------------------------
                        try:
                            local_path = self._download_url(
                                found["url"],
                                download_folder
                            )

                            downloaded_count += 1

                            self._queue_log(
                                f"DOWNLOADED: {Path(local_path).name}"
                            )
                            self._queue_log(
                                f"SAVED TO  : {local_path}"
                            )

                        except Exception as e:
                            failed_count += 1
                            self._queue_log(
                                f"ERROR: Download failed for {found['url']}"
                            )
                            self._queue_log(
                                f"ERROR DETAIL: {e}"
                            )

            # --------------------------------------------------
            self._queue_log("=" * 72)
            self._queue_log("Download process finished.")
            self._queue_log(f"Found      : {found_count}")
            self._queue_log(f"Downloaded : {downloaded_count}")
            self._queue_log(f"Missing    : {missing_count}")
            self._queue_log(f"Failed     : {failed_count}")
            self._queue_log("=" * 72)

        except Exception as e:
            self._queue_log("ERROR: Unexpected download worker error.")
            self._queue_log(str(e))


    def select_download_folder(self):
        folder = filedialog.askdirectory(
            title="Select Download Folder",
            initialdir=self.download_folder_var.get()
        )
        if folder:
            self.download_folder_var.set(folder)



    def log_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")

        self.info_text.configure(state="normal")
        self.info_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.info_text.see(tk.END)
        self.info_text.configure(state="disabled")

        self.info_text.update_idletasks() 

    def _queue_log(self, message):
        self._log_queue.put(message)


    def _poll_log_queue(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get()
            self.log_message(msg)

        if self._download_thread is not None and self._download_thread.is_alive():
            self.parent.after(100, self._poll_log_queue)
        else:
            while not self._log_queue.empty():
                msg = self._log_queue.get()
                self.log_message(msg)

            self._download_thread = None          

    def clear_info(self):
        """Clear the Information panel."""
        self.info_text.configure(state="normal")
        self.info_text.delete("1.0", tk.END)
        self.info_text.configure(state="disabled")


    def kill_process(self):
        self._cancel_requested = True
        try:
            if self._active_response is not None:
                self._active_response.close()
        except Exception:
            pass

        try:
            if self._active_session is not None:
                self._active_session.close()
        except Exception:
            pass
        self.log_message("Cancel requested. Current file will stop after the active download/check step.")


    def _gps_week_dow(self, dt):
        gps_epoch = date(1980, 1, 6)
        gps_days = (dt - gps_epoch).days
        return gps_days // 7, gps_days % 7


    def _sampling_seconds(self, sampling):
        unit = sampling[-1].upper()
        value = int(sampling[:-1])

        if unit == "S":
            return value
        if unit == "M":
            return value * 60
        if unit == "H":
            return value * 3600
        if unit == "D":
            return value * 86400

        return 10**9


    def _length_days(self, length):
        try:
            return int(length[:-1])
        except Exception:
            return 999



    def _ftps_context(self):
        """Create a permissive SSL context for archives with self-signed/expired certificates."""
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx


    def _open_ftp_connection(self, parsed_url, timeout=30, use_tls=False, retries=3):
        """Open FTP/FTPS connection with retry support.

        For FTPS, implicit TLS on port 990 is used by default. This is required
        for bdspride.com/WCC PRIDE. If a URL explicitly uses another port, the
        same implicit connection is tried first; this keeps the behavior robust
        for servers whose URL is written as ftps://host/path without :990.
        """
        host = parsed_url.hostname
        if not host:
            raise RuntimeError("FTP host is empty.")

        port = parsed_url.port or (990 if use_tls else 21)
        username = parsed_url.username or "anonymous"
        password = parsed_url.password or "anonymous@example.com"

        last_error = None

        for attempt in range(1, retries + 1):
            ftp = None
            try:
                if use_tls:
                    ftp = ImplicitFTP_TLS(context=self._ftps_context(), timeout=timeout)
                else:
                    ftp = FTP(timeout=timeout)

                # FileZilla behavior: ignore unroutable PASV IP and use control host.
                if hasattr(ftp, "trust_server_pasv_ipv4_address"):
                    ftp.trust_server_pasv_ipv4_address = False

                ftp.connect(host, port, timeout=timeout)
                ftp.login(username, password)

                if use_tls:
                    ftp.prot_p()

                ftp.set_pasv(True)
                return ftp

            except Exception as e:
                last_error = e
                try:
                    if ftp is not None:
                        ftp.close()
                except Exception:
                    pass

                # bdspride sometimes closes the first TLS session; retry like FileZilla.
                if attempt < retries:
                    time.sleep(0.7 * attempt)
                    continue

        raise last_error

    def _url_exists(self, url, timeout=10):
        """
        Check a single product URL directly.

        Important: do not reuse the directory-listing cache here. If a directory
        listing failed once and was cached as None, using that cache would make
        every fallback existence check return False.
        """
        scheme = urlparse(url).scheme.lower()

        if scheme in ("http", "https"):
            try:
                r = requests.head(url, allow_redirects=True, timeout=timeout)
                if r.status_code == 200:
                    return True
                if r.status_code not in (403, 405):
                    return False

                # Some archives do not support HEAD. Try a tiny streamed GET.
                with requests.get(url, stream=True, timeout=timeout) as g:
                    return g.status_code == 200
            except Exception:
                return False

        if scheme in ("ftp", "ftps"):
            p = urlparse(url)
            folder = os.path.dirname(p.path) or "/"
            filename = os.path.basename(p.path)
            ftp = None

            try:
                ftp = self._open_ftp_connection(
                    p,
                    timeout=timeout,
                    use_tls=(scheme == "ftps"),
                    retries=3
                )

                ftp.cwd(folder)

                try:
                    ftp.size(filename)
                    return True
                except Exception:
                    try:
                        return filename in {os.path.basename(x.rstrip("/")) for x in ftp.nlst(filename)}
                    except Exception:
                        return False

            except Exception:
                return False

            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass

        return False


    def _list_directory(self, base_url, timeout=15):
        base_url = base_url.rstrip("/")

        if base_url in self._archive_listing_cache:
            return self._archive_listing_cache[base_url]

        scheme = urlparse(base_url).scheme.lower()

        if scheme in ("http", "https"):
            files = self._list_http_directory(base_url, timeout)

        elif scheme == "ftp":
            files = self._list_ftp_directory(base_url, timeout, use_tls=False)

        elif scheme == "ftps":
            files = self._list_ftp_directory(base_url, timeout, use_tls=True)

        else:
            files = None

        self._archive_listing_cache[base_url] = files
        return files


    def _list_http_directory(self, base_url, timeout=15):
        try:
            r = requests.get(base_url + "/", timeout=timeout)
            r.raise_for_status()

            names = set(re.findall(r'href=["\']([^"\']+)["\']', r.text))
            return {os.path.basename(x.rstrip("/")) for x in names if x and not x.startswith("?")}

        except Exception:
            return None


    def _list_ftp_directory(self, base_url, timeout=15, use_tls=False):
        p = urlparse(base_url)

        folder = p.path or "/"

        ftp = None

        try:
            ftp = self._open_ftp_connection(
                p,
                timeout=timeout,
                use_tls=use_tls,
                retries=3
            )

            ftp.cwd(folder)
            files = ftp.nlst()

            return {os.path.basename(x.rstrip("/")) for x in files}

        except Exception:
            return None

        finally:
            try:
                if ftp is not None:
                    ftp.quit()
            except Exception:
                pass

    def _v3_product_codes(self, file_type):
        """
        IGS v3 long filename product-code candidates.
        """

        return {
            "SP3": ["ORB.SP3"],
            "CLK": ["CLK.CLK"],
            "ERP": ["ERP.ERP"],
            "BIA": ["OSB.BIA", "BIA.BIA"],
            "OBX": ["ATT.OBX", "OBX.OBX"],
        }.get(file_type, [])


    def _v2_extension(self, file_type):
        return {
            "SP3": "sp3",
            "CLK": "clk",
            "ERP": "erp",
            "BIA": "bia",
            "OBX": "obx",
        }.get(file_type)


    def _default_v3_options(self, file_type):
        """
        En yüksek örneklem öncelikli olacak şekilde sıralanacak adaylar.
        """

        if file_type == "SP3":
            return ["0000"], ["01D", "02D", "03D", "07D"], ["05M", "15M"]
        if file_type == "CLK":
            return ["0000", "0600", "1200", "1800"], ["01D", "02D", "03D", "07D"], ["05S", "30S"]
        if file_type == "ERP":
            return ["0000", "0600", "1200", "1800"], ["01D", "02D", "03D", "07D"], ["12H", "01D"]
        if file_type == "BIA":
            return ["0000"], ["01D", "02D", "03D", "07D"], ["01D"]
        if file_type == "OBX":
            return ["0000"], ["01D", "02D", "03D", "07D"], ["30S", "05M"]

        return ["0000"], ["01D"], ["01D"]


    def _build_v3_candidates(self, prefix, dt, file_type):
        doy = dt.timetuple().tm_yday
        times, lengths, samplings = self._default_v3_options(file_type)
        product_codes = self._v3_product_codes(file_type)

        candidates = []

        for sampling in samplings:
            for length in lengths:
                for time_str in times:
                    for product_code in product_codes:
                        base = (
                            f"{prefix}_"
                            f"{dt.year}{doy:03d}{time_str}_"
                            f"{length}_{sampling}_"
                            f"{product_code}"
                        )

                        for ext in [".gz", ".Z", ""]:
                            candidates.append({
                                "filename": base + ext,
                                "version": "v3",
                                "sampling": sampling,
                                "length": length,
                                "sampling_sec": self._sampling_seconds(sampling),
                                "length_days": self._length_days(length),
                            })

        candidates.sort(
            key=lambda x: (
                x["sampling_sec"],     # önce yüksek örneklem
                x["length_days"],      # eşitse kısa length
                x["filename"]
            )
        )

        return candidates


    def _build_v2_candidates(self, prefix, dt, file_type):
        ext = self._v2_extension(file_type)
        if not ext:
            return []

        gps_week, gps_dow = self._gps_week_dow(dt)
        short_prefix = prefix[:3].lower()

        return [
            {
                "filename": f"{short_prefix}{gps_week:04d}{gps_dow}.{ext}.Z",
                "version": "v2",
                "sampling": "N/A",
                "length": "N/A",
                "sampling_sec": 999999,
                "length_days": 999,
            },
            {
                "filename": f"{short_prefix}{gps_week:04d}{gps_dow}.{ext}.gz",
                "version": "v2",
                "sampling": "N/A",
                "length": "N/A",
                "sampling_sec": 999999,
                "length_days": 999,
            },
            {
                "filename": f"{short_prefix}{gps_week:04d}{gps_dow}.{ext}",
                "version": "v2",
                "sampling": "N/A",
                "length": "N/A",
                "sampling_sec": 999999,
                "length_days": 999,
            },
        ]


    def _archive_candidate_urls(self, archive_names, dt):
        """Return available archive base URLs for a given date in user-defined order."""
        for archive_name in archive_names:
            archive_obj = ARCHIVE_URLS.get(archive_name)
            if archive_obj is None:
                self._queue_log(f"  SKIP archive: {archive_name} is not defined.")
                continue

            try:
                base_url = archive_obj.date(dt).rstrip("/")
            except Exception as e:
                self._queue_log(f"  SKIP archive: {archive_name} date URL failed: {e}")
                continue

            yield archive_name, base_url


    def _list_archive_files(self, base_url, timeout=15):
        """
        Read one archive directory listing and cache its file names.

        This wrapper must support http/https/ftp/ftps. The previous version used
        urllib.urlopen() directly; that is unreliable for FTPS and caused all
        WCCpride/WUMpride-style archives to be cached as None, so every product
        was reported as NOT FOUND.
        """
        files = self._list_directory(base_url, timeout=timeout)

        if files is None:
            self._queue_log(f"  WARNING: archive listing failed: {base_url}")
        else:
            self._queue_log(f"  Cached archive listing: {base_url} ({len(files)} files)")

        return files


    def _candidate_found_in_archive(self, base_url, cand, file_set):
        """Return full URL if candidate exists in archive; otherwise None."""
        if self._cancel_requested:
            return None

        filename = cand["filename"]
        url = f"{base_url}/{filename}"

        if file_set is not None:
            return url if filename in file_set else None

        # Directory listing unavailable: fallback to single-file existence check.
        return url if self._url_exists(url, timeout=5) else None


    def _find_best_file_url(self, archive_names, prefix, dt, file_type, allow_v2):
        """
        Try v3 long filenames first. If no v3 product exists and allow_v2=True,
        try short v2 filenames. Candidates are sorted by highest sampling rate.

        Optimized behavior:
        - Query each date/archive directory once.
        - Match all candidate filenames locally from the cached directory listing.
        - Fallback to HEAD/GET only if the server does not expose a listing.
        """

        v3_candidates = self._build_v3_candidates(prefix, dt, file_type)

        for archive_name, base_url in self._archive_candidate_urls(archive_names, dt):
            file_set = self._list_archive_files(base_url)

            for cand in v3_candidates:
                url = self._candidate_found_in_archive(base_url, cand, file_set)
                if self._cancel_requested:
                    return None
                if url:
                    return {
                        "archive": archive_name,
                        "url": url,
                        **cand
                    }

        if not allow_v2:
            return None

        v2_candidates = self._build_v2_candidates(prefix, dt, file_type)

        for archive_name, base_url in self._archive_candidate_urls(archive_names, dt):
            file_set = self._list_archive_files(base_url)

            for cand in v2_candidates:
                url = self._candidate_found_in_archive(base_url, cand, file_set)
                if self._cancel_requested:
                    return None
                if url:
                    return {
                        "archive": archive_name,
                        "url": url,
                        **cand
                    }

        return None


    def _download_url(self, url, download_folder):
        os.makedirs(download_folder, exist_ok=True)

        filename = os.path.basename(url)
        local_path = os.path.join(download_folder, filename)
        tmp_path = local_path + ".part"

        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            self._queue_log(f"SKIP: already exists -> {filename}")
            return local_path

        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        scheme = urlparse(url).scheme.lower()

        if scheme in ("http", "https"):
            return self._download_http(url, local_path, tmp_path)

        elif scheme in ("ftp", "ftps"):
            return self._download_ftp(url, local_path, tmp_path, use_tls=(scheme == "ftps"))

        else:
            raise RuntimeError(f"Unsupported URL scheme: {scheme}")

        
    def _download_http(self, url, local_path, tmp_path):
        self._active_session = requests.Session()

        try:
            with self._active_session.get(url, stream=True, timeout=30) as r:
                self._active_response = r
                r.raise_for_status()

                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if self._cancel_requested:
                            raise RuntimeError("Download cancelled by user.")

                        if chunk:
                            f.write(chunk)

            os.replace(tmp_path, local_path)
            return local_path

        finally:
            self._active_response = None

            try:
                self._active_session.close()
            except Exception:
                pass

            self._active_session = None

            if self._cancel_requested and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


    def _download_ftp(self, url, local_path, tmp_path, use_tls=False):
        p = urlparse(url)

        folder = os.path.dirname(p.path)
        filename = os.path.basename(p.path)

        ftp = None

        try:
            ftp = self._open_ftp_connection(
                p,
                timeout=30,
                use_tls=use_tls,
                retries=3
            )

            ftp.cwd(folder)

            with open(tmp_path, "wb") as f:

                def callback(data):
                    if self._cancel_requested:
                        raise RuntimeError("Download cancelled by user.")
                    f.write(data)

                ftp.retrbinary(f"RETR {filename}", callback, blocksize=1024 * 1024)

            os.replace(tmp_path, local_path)
            return local_path

        finally:
            try:
                if ftp is not None:
                    ftp.close()
            except Exception:
                pass

            if self._cancel_requested and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass