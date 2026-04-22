import sqlite3
from datetime import datetime
import math

DB_PATH = 'inflow_outflow.db'

class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spt (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                year_endorsed TEXT,
                content_type TEXT,
                fte_requirement TEXT,
                remaining_fte_capacity TEXT,
                frequency TEXT,
                spt TEXT,
                average_volume TEXT,
                working_minutes TEXT,
                status TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS content_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS efficiencies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_title TEXT,
                generated_capacity TEXT,
                project_type TEXT,
                status TEXT,
                year TEXT,
                project_owner TEXT
            )
        """)
        # Ensure project_owner column exists for upgrades
        try:
            self.conn.execute("ALTER TABLE efficiencies ADD COLUMN project_owner TEXT")
        except Exception:
            pass
        # Ensure expanded efficiencies fields exist for upgrades
        for column_name in [
            'description',
            'planned_deployment',
            'savings',
            'team',
            'project_lead',
            'domestic_reph',
            'gptrac',
            'remarks',
            'content_process'
        ]:
            try:
                self.conn.execute(f"ALTER TABLE efficiencies ADD COLUMN {column_name} TEXT")
            except Exception:
                pass
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spt_settings (
                category TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spt_settings_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                changed_at TEXT,
                changed_by TEXT
            )
        """)
        try:
            self.conn.execute("ALTER TABLE spt_settings_history ADD COLUMN changed_by TEXT")
        except Exception:
            pass
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS spt_change_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spt_id INTEGER,
                changed_by TEXT,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                comment TEXT,
                changed_at TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        defaults = [
            "Attorney", "Judges", "Metrics Scoring", "Expert Witness", "MAAN-MACL", "Company Resolution"
        ]
        for ct in defaults:
            try:
                self.conn.execute("INSERT INTO content_types (name) VALUES (?)", (ct,))
            except sqlite3.IntegrityError:
                pass
        if self.conn.execute("SELECT COUNT(*) FROM spt_settings").fetchone()[0] == 0:
            spt_defaults = [
                "R2D2", "Judge Maintenance", "Attorney Duplicate", "Metrics", "Agency Judges",
                "URL Redirect", "UK Law Firm", "Google Maps Review", "Special Project",
                "Company Reso", "M&A Backlog", "MAAN/MACL Matching", "EW Linking",
                "Dup Reso_CorpDept."
            ]
            for d in spt_defaults:
                self.conn.execute("INSERT INTO spt_settings (category, value) VALUES (?, ?)", (d, ""))
        self.conn.commit()

    # SPT CRUD
    def get_spt(self, filters=None):
        query = """
            SELECT s.id, s.year_endorsed, s.content_type, s.fte_requirement, s.remaining_fte_capacity, 
                   s.frequency, COALESCE(ss.value, s.spt) as spt, s.average_volume, s.working_minutes, s.status
            FROM spt s
            LEFT JOIN spt_settings ss ON s.content_type = ss.category
            WHERE 1=1
        """
        params = []
        if filters:
            if 'status' in filters and filters['status']:
                query += " AND s.status=?"
                params.append(filters['status'])
            if 'year' in filters and filters['year']:
                query += " AND substr(s.year_endorsed, 1, 4)=?"
                params.append(filters['year'])
            if 'month' in filters and filters['month']:
                query += " AND substr(s.year_endorsed, 6, 2)=?"
                params.append(filters['month'])
            if 'exact_date' in filters and filters['exact_date']:
                query += " AND (CASE " \
                         "WHEN length(s.year_endorsed) = 10 THEN s.year_endorsed " \
                         "WHEN length(s.year_endorsed) = 7 THEN s.year_endorsed || '-01' " \
                         "ELSE s.year_endorsed || '-01-01' END)=?"
                params.append(filters['exact_date'])
            if 'from_date' in filters and 'to_date' in filters and filters['from_date'] and filters['to_date']:
                query += " AND (CASE " \
                         "WHEN length(s.year_endorsed) = 10 THEN s.year_endorsed " \
                         "WHEN length(s.year_endorsed) = 7 THEN s.year_endorsed || '-01' " \
                         "ELSE s.year_endorsed || '-01-01' END) BETWEEN ? AND ?"
                params.append(filters['from_date'])
                params.append(filters['to_date'])
        return self.conn.execute(query, params).fetchall()

    def add_spt(self, data):
        self.conn.execute("""
            INSERT INTO spt (year_endorsed, content_type, fte_requirement, remaining_fte_capacity, frequency, spt, average_volume, working_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(data.values()))
        self.conn.commit()

    def update_spt(self, row_id, data):
        self.conn.execute("""
            UPDATE spt SET year_endorsed=?, content_type=?, fte_requirement=?, remaining_fte_capacity=?, frequency=?, spt=?, average_volume=?, working_minutes=?, status=? WHERE id=?
        """, tuple(data.values()) + (row_id,))
        self.conn.commit()

    def log_spt_change(self, spt_id, changed_by, field, old_value, new_value, comment=''):
        if not changed_by:
            changed_by = 'Unknown User'
        changed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.conn.execute(
            """
            INSERT INTO spt_change_log (spt_id, changed_by, field, old_value, new_value, comment, changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (spt_id, changed_by, field, old_value, new_value, comment, changed_at)
        )
        self.conn.commit()

    def get_spt_change_history(self, spt_id, limit=50):
        return self.conn.execute(
            """
            SELECT changed_by, field, old_value, new_value, comment, changed_at
            FROM spt_change_log
            WHERE spt_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (spt_id, limit)
        ).fetchall()

    def delete_spt(self, row_id):
        self.conn.execute("DELETE FROM spt WHERE id=?", (row_id,))
        self.conn.commit()    # Efficiencies CRUD
    def get_efficiencies(self, year=None, filters=None):
        query = "SELECT * FROM efficiencies WHERE 1=1"
        params = []
        if filters:
            if 'year' in filters and filters['year']:
                query += " AND year=?"
                params.append(filters['year'])
            if 'exact_date' in filters and filters['exact_date']:
                query += " AND (CASE " \
                         "WHEN length(year) = 10 THEN year " \
                         "WHEN length(year) = 7 THEN year || '-01' " \
                         "ELSE year || '-01-01' END)=?"
                params.append(filters['exact_date'])
            if 'from_date' in filters and 'to_date' in filters and filters['from_date'] and filters['to_date']:
                query += " AND (CASE " \
                         "WHEN length(year) = 10 THEN year " \
                         "WHEN length(year) = 7 THEN year || '-01' " \
                         "ELSE year || '-01-01' END) BETWEEN ? AND ?"
                params.append(filters['from_date'])
                params.append(filters['to_date'])
        elif year:
            query += " AND year=?"
            params.append(year)
        return self.conn.execute(query, params).fetchall()

    def add_efficiency(self, data):
        self.conn.execute("""
            INSERT INTO efficiencies (
                project_title, generated_capacity, project_type, status, year, project_owner,
                description, planned_deployment, savings, team, project_lead, domestic_reph, gptrac, remarks, content_process
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(data.values()))
        self.conn.commit()

    def update_efficiency(self, row_id, data):
        self.conn.execute("""
            UPDATE efficiencies SET
                project_title=?, generated_capacity=?, project_type=?, status=?, year=?, project_owner=?,
                description=?, planned_deployment=?, savings=?, team=?, project_lead=?, domestic_reph=?, gptrac=?, remarks=?, content_process=?
            WHERE id=?
        """, tuple(data.values()) + (row_id,))
        self.conn.commit()

    def update_efficiency_remarks(self, row_id, remarks):
        self.conn.execute("UPDATE efficiencies SET remarks=? WHERE id=?", (remarks, row_id))
        self.conn.commit()

    def delete_efficiency(self, row_id):
        self.conn.execute("DELETE FROM efficiencies WHERE id=?", (row_id,))
        self.conn.commit()

    # Headcount
    def get_headcount(self):
        row = self.conn.execute("SELECT value FROM app_settings WHERE key='headcount'").fetchone()
        return row[0] if row else ''

    def set_headcount(self, value):
        self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ('headcount', str(value)))
        self.conn.commit()

    # SPT Settings
    def get_spt_settings(self):
        return self.conn.execute("SELECT category, value FROM spt_settings ORDER BY category").fetchall()

    def update_spt_settings(self, settings):
        self.conn.execute("DELETE FROM spt_settings")
        self.conn.executemany("INSERT INTO spt_settings (category, value) VALUES (?, ?)", settings)
        self.conn.commit()

    def log_spt_settings_changes(self, old_settings, new_settings, comment='', changed_by='Unknown User'):
        old_map = {cat: (val or '') for cat, val in old_settings}
        new_map = {cat: (val or '') for cat, val in new_settings}
        changed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        history_rows = []

        changed_by = str(changed_by).strip() or 'Unknown User'
        for category in sorted(set(old_map.keys()) | set(new_map.keys())):
            old_val = old_map.get(category, '')
            new_val = new_map.get(category, '')
            if old_val != new_val:
                history_rows.append((category, old_val, new_val, comment, changed_at, changed_by))

        if history_rows:
            self.conn.executemany(
                """
                INSERT INTO spt_settings_history (category, old_value, new_value, comment, changed_at, changed_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                history_rows
            )
            self.conn.commit()

    def log_spt_settings_history_entries(self, entries):
        if not entries:
            return

        changed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        history_rows = []
        for entry in entries:
            category = entry.get('category', '')
            old_value = entry.get('old_value', '')
            new_value = entry.get('new_value', '')
            comment = entry.get('comment', '')
            changed_by = str(entry.get('changed_by', 'Unknown User')).strip() or 'Unknown User'
            history_rows.append((category, old_value, new_value, comment, changed_at, changed_by))

        self.conn.executemany(
            """
            INSERT INTO spt_settings_history (category, old_value, new_value, comment, changed_at, changed_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            history_rows
        )
        self.conn.commit()

    def get_spt_settings_history(self, limit=100):
        return self.conn.execute(
            """
            SELECT id, category, old_value, new_value, comment, changed_at, changed_by
            FROM spt_settings_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    def delete_spt_settings_history_entry(self, history_id):
        self.conn.execute("DELETE FROM spt_settings_history WHERE id=?", (history_id,))
        self.conn.commit()

    def add_spt_category(self, category):
        try:
            self.conn.execute("INSERT INTO spt_settings (category, value) VALUES (?, ?)", (category, ""))
            self.conn.commit()
        except sqlite3.IntegrityError:
            pass

    def delete_spt_category(self, category):
        self.conn.execute("DELETE FROM spt_settings WHERE category=?", (category,))
        self.conn.commit()

    # Frequency Settings (Daily, Weekly, Monthly working minutes)
    def get_frequency_settings(self):
        # Default values if not set
        defaults = {
            'Daily': '109200',
            'Weekly': '21840',
            'Monthly': '5040'
        }
        frequencies = {}
        for freq_name in ['Daily', 'Weekly', 'Monthly']:
            row = self.conn.execute("SELECT value FROM app_settings WHERE key=?", (f'frequency_{freq_name}',)).fetchone()
            if row and row[0]:
                frequencies[freq_name] = row[0]
            else:
                frequencies[freq_name] = defaults[freq_name]
        return frequencies

    def set_frequency_setting(self, frequency_name, minutes):
        self.conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (f'frequency_{frequency_name}', str(minutes)))
        self.conn.commit()

    # Metrics
    def get_metrics(self, year=None):
        def round_up_2(x):
            return math.ceil(float(x) * 100) / 100 if x is not None else 0.00

        params = []
        year_filter = ""
        if year:
            year_filter = " WHERE substr(year_endorsed, 1, 4) = ?"
            params.append(year)

        total_fte_query = "SELECT SUM(CAST(fte_requirement as FLOAT)) FROM spt" + year_filter
        total_fte = round_up_2(self.conn.execute(total_fte_query, params).fetchone()[0] or 0)

        inflow_filter = " WHERE status='Inflow'"
        if year:
            inflow_filter += " AND substr(year_endorsed, 1, 4) = ?"
        else:
            params = [] # Reset params if no year but we need to run another query
        total_inflow_query = "SELECT SUM(CAST(fte_requirement as FLOAT)) FROM spt" + inflow_filter
        total_inflow = round_up_2(self.conn.execute(total_inflow_query, [year] if year else []).fetchone()[0] or 0)

        outflow_filter = " WHERE status='Outflow'"
        if year:
            outflow_filter += " AND substr(year_endorsed, 1, 4) = ?"
        total_outflow_query = "SELECT SUM(ABS(CAST(fte_requirement as FLOAT))) FROM spt" + outflow_filter
        total_outflow = round_up_2(self.conn.execute(total_outflow_query, [year] if year else []).fetchone()[0] or 0)
        
        eff_params = []
        eff_year_filter = ""
        if year:
            eff_year_filter = " WHERE year = ?"
            eff_params.append(year)
        eff_total_query = "SELECT SUM(CAST(generated_capacity as FLOAT)) FROM efficiencies" + eff_year_filter
        eff_total = round_up_2(self.conn.execute(eff_total_query, eff_params).fetchone()[0] or 0)

        headcount = round_up_2(self.get_headcount() or 0)
        diff = round_up_2(headcount - total_fte)
        
        return {
            'total_fte': f"{total_fte:.2f}",
            'total_inflow': f"{total_inflow:.2f}",
            'total_outflow': f"{total_outflow:.2f}",
            'eff_total': f"{eff_total:.2f}",
            'headcount': f"{headcount:.2f}",
            'overstaffed': diff > 0,
            'diff': f"{diff:.2f}"
        }

    def get_content_type_summary(self, year=None, filters=None):
        def round_up_2(x):
            return math.ceil(float(x) * 100) / 100 if x is not None else 0.00
        
        query = "SELECT content_type, SUM(CAST(fte_requirement as FLOAT)) FROM spt"
        params = []
        conditions = []
        if filters:
            if 'status' in filters and filters['status']:
                conditions.append("status=?")
                params.append(filters['status'])
            if 'year' in filters and filters['year']:
                conditions.append("substr(year_endorsed, 1, 4)=?")
                params.append(filters['year'])
            if 'month' in filters and filters['month']:
                conditions.append("substr(year_endorsed, 6, 2)=?")
                params.append(filters['month'])
            if 'exact_date' in filters and filters['exact_date']:
                conditions.append("(CASE WHEN length(year_endorsed) = 10 THEN year_endorsed WHEN length(year_endorsed) = 7 THEN year_endorsed || '-01' ELSE year_endorsed || '-01-01' END)=?")
                params.append(filters['exact_date'])
            if 'from_date' in filters and 'to_date' in filters and filters['from_date'] and filters['to_date']:
                conditions.append("(CASE WHEN length(year_endorsed) = 10 THEN year_endorsed WHEN length(year_endorsed) = 7 THEN year_endorsed || '-01' ELSE year_endorsed || '-01-01' END) BETWEEN ? AND ?")
                params.append(filters['from_date'])
                params.append(filters['to_date'])
        elif year:
            conditions.append("substr(year_endorsed, 1, 4)=?")
            params.append(year)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " GROUP BY content_type"
        
        rows = self.conn.execute(query, params).fetchall()
        return [(ctype, f"{round_up_2(fte):.2f}") for ctype, fte in rows]

    def get_distinct_years(self):
        return self.conn.execute("SELECT DISTINCT substr(year_endorsed, 1, 4) as year_endorsed FROM spt ORDER BY year_endorsed DESC").fetchall()
