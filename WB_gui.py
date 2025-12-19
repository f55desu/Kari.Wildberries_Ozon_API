import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
from os import getenv
from threading import Thread
from threading import Event

from wb_api import Campaing_WB

from dotenv import load_dotenv

load_dotenv() # Load variables from .env

API_KEY = getenv("API_KEY_RU")

# === Импортируй свои функции отсюда ===
# from wb_api_module import get_promotion_count_df, get_promotion_adverts_df, build_final_df
# Если функции в этом же файле — импорт не нужен.

# --- Справочник типов кампаний (можешь переименовать под себя) ---

# --- Статусы, если нужны в UI (не обязательно) ---
STATUS_MAP = {
    4: "готова к запуску",
    7: "завершена",
    8: "отменена",
    9: "активна",
    11: "на паузе",
}


class ExportApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Выгрузка кампаний WB")
        self.geometry("800x600")
        self.resizable(False, False)

        # state
        self.type_vars = {t: tk.BooleanVar(value=(t in (4, 7, 8, 9, 11))) for t in STATUS_MAP}
        self.file_path_var = tk.StringVar(value="")
        self.api_key_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Выберите типы, путь файла и нажмите «Выгрузить».")
        self.stop_event = Event()

        self._build_ui()

    def _build_ui(self):
        padding = {"padx": 12, "pady": 8}

        # # API key frame
        frm_key = ttk.LabelFrame(self, text="Внимание!")
        frm_key.pack(fill="x", **padding)

        ttk.Label(frm_key, text='Не забудьте прописать API_KEY_RU="[Ваш API токен от WB Seller]" в файле .env, если его нет - создайте в одной папке с данной программой.', wraplength=650, justify="left").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        # ent = ttk.Entry(frm_key, textvariable=self.api_key_var, width=70, show="*")
        # ent.grid(row=0, column=1, sticky="w", padx=10, pady=8)

        # Types frame
        frm_types = ttk.LabelFrame(self, text="Типы кампаний")
        frm_types.pack(fill="x", **padding)

        # чекбоксы в две колонки
        cols = 2
        r = 0
        c = 0
        for t, name in STATUS_MAP.items():
            cb = ttk.Checkbutton(frm_types, text=f"{t} — {name}", variable=self.type_vars[t])
            cb.grid(row=r, column=c, sticky="w", padx=10, pady=4)
            c += 1
            if c >= cols:
                c = 0
                r += 1

        # File frame
        frm_file = ttk.LabelFrame(self, text="Файл выгрузки")
        frm_file.pack(fill="x", **padding)

        ttk.Label(frm_file, text="Путь к Excel (.xlsx):").grid(row=0, column=0, sticky="w", padx=10, pady=8)
        ent_file = ttk.Entry(frm_file, textvariable=self.file_path_var, width=60)
        ent_file.grid(row=0, column=1, sticky="w", padx=10, pady=8)
        btn_browse = ttk.Button(frm_file, text="Выбрать…", command=self.choose_file)
        btn_browse.grid(row=0, column=2, sticky="w", padx=10, pady=8)

        # Actions
        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", **padding)

        self.btn_export = ttk.Button(frm_actions, text="Выгрузить", command=self.on_export_clicked)
        self.btn_export.pack(side="left", padx=10)

        self.btn_stop = ttk.Button(frm_actions, text="Стоп", command=self.on_stop_clicked, state="disabled")
        self.btn_stop.pack(side="left", padx=10)

        self.btn_quit = ttk.Button(frm_actions, text="Выход", command=self.destroy)
        self.btn_quit.pack(side="left", padx=10)

        # Status / log
        frm_status = ttk.LabelFrame(self, text="Статус")
        frm_status.pack(fill="both", expand=True, **padding)

        self.txt_log = tk.Text(frm_status, height=10, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=10)
        self._log(self.status_var.get())

    def _log(self, msg: str):
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.update_idletasks()

    def choose_file(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")],
            title="Сохранить выгрузку как…"
        )
        if path:
            self.file_path_var.set(path)

    def _get_selected_types(self):
        return [STATUS_MAP[t] for t, var in self.type_vars.items() if var.get()]

    def on_export_clicked(self):
        api_key = API_KEY
        if not api_key:
            messagebox.showerror("Ошибка", "Укажи API Key. В файле .env")
            return

        selected_types = self._get_selected_types()
        print(selected_types)
        if not selected_types:
            messagebox.showerror("Ошибка", "Выбери хотя бы один тип кампаний.")
            return

        out_path = self.file_path_var.get().strip()
        if not out_path:
            messagebox.showerror("Ошибка", "Выбери путь сохранения Excel-файла.")
            return

        # disable UI during export
        self.btn_export.config(state="disabled")
        self._log(f"Старт выгрузки. Типы: {selected_types}. Файл: {out_path}")

        self.stop_event.clear()
        self.btn_export.config(state="disabled")
        self.btn_stop.config(state="normal")

        # run in background thread (чтобы UI не зависал)
        thread = Thread(
            target=self._run_export,
            args=(api_key, selected_types, out_path),
            daemon=True
        )
        thread.start()
    
    def on_stop_clicked(self):
        self.stop_event.set()
        self._log("⛔ Остановка запрошена пользователем. Завершаю после текущей операции…")
        self.btn_stop.config(state="disabled")


    def _run_export(self, api_key: str, selected_types: list[int], out_path: str):
        try:
            if self.stop_event.is_set():
                self._log("Остановлено до старта.")
                return

            self._log("1/4 Получаю список кампаний (/promotion/count)…")
            df_count = Campaing_WB.get_promotion_count_df(api_key)

            if self.stop_event.is_set():
                self._log("Остановлено пользователем.")
                return

            if df_count is None or df_count.empty:
                self._log("Кампаний нет. Завершено.")
                messagebox.showinfo("Готово", "Кампаний не найдено.")
                return

            self._log("2/4 Фильтрую кампании по выбранным типам…")
            df_count_filtered = df_count[df_count["status_name"].isin(selected_types)].copy()

            self._log(
                f"Найдено кампаний (всего): {df_count['advertId'].nunique()} | "
                f"после фильтра: {df_count_filtered['advertId'].nunique()}"
            )

            if self.stop_event.is_set():
                self._log("Остановлено пользователем.")
                return

            if df_count_filtered.empty:
                self._log("После фильтрации кампаний нет. Завершено.")
                messagebox.showinfo("Готово", "По выбранным типам кампаний нет.")
                return

            self._log("3/4 Получаю детализацию кампаний (/promotion/adverts)…")

            # ВАЖНО: передаем stop_event внутрь функции выгрузки (ниже покажу как её изменить)
            df_adv = Campaing_WB.get_promotion_adverts_df(api_key, df_count_filtered, stop_event=self.stop_event, ui_log=self._log)

            if self.stop_event.is_set():
                self._log("Остановлено пользователем. Данные не сохраняю.")
                return

            if df_adv is None or df_adv.empty:
                self._log("Детализация пустая. Сохраняю только df_count_filtered.")
                df_count_filtered.to_excel(out_path, index=False)
                messagebox.showinfo("Готово", "Детализация не получена. Сохранён только список кампаний.")
                return

            # Вот тот принт — в статус
            self._log(
                f"[DF] rows={len(df_adv)} unique_advertId={df_adv['advertId'].nunique()} "
                f"unique_nms={(df_adv['nms'].nunique() if 'nms' in df_adv.columns else 'NA')}"
            )

            self._log("4/4 Собираю финальный датафрейм и сохраняю Excel…")
            df_final = Campaing_WB.build_final_df(df_count_filtered, df_adv)

            if self.stop_event.is_set():
                self._log("Остановлено пользователем. Данные не сохраняю.")
                return

            df_final.to_excel(out_path, index=False)

            self._log(f"Готово. Строк: {len(df_final)} | advertId: {df_final['advertId'].nunique()}")
            messagebox.showinfo("Готово", f"Выгрузка завершена.\nФайл: {out_path}")

        except Exception as e:
            self._log(f"❌ Ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))
        finally:
            self.btn_export.config(state="normal")
            self.btn_stop.config(state="disabled")


# ===== Запуск приложения =====
if __name__ == "__main__":
    app = ExportApp()
    app.mainloop()
