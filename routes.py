from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from auth import login_required, requires_role, get_current_user, csrf_protect
from models import Database
import math

main_bp = Blueprint('main', __name__)
db = Database()

def build_endorsed_date(year_value, month_value, day_value):
    year_part = (year_value or '').strip()
    month_part = (month_value or '').strip().zfill(2)
    day_part = (day_value or '').strip().zfill(2)
    if year_part and month_part and day_part:
        return f"{year_part}-{month_part}-{day_part}"
    if year_part and month_part:
        return f"{year_part}-{month_part}"
    return year_part

def format_savings_value(raw_value):
    value = (raw_value or '').strip()
    if not value:
        return ''
    if value.startswith('$'):
        return value
    return f"${value}"


def format_generated_capacity_value(raw_value):
    numeric_value = parse_numeric_text(raw_value)
    if numeric_value == 0 and not str(raw_value or '').strip():
        return ''
    return f"{numeric_value:.2f}".rstrip('0').rstrip('.')


def get_effective_user_name():
    current_user = get_current_user() or session.get('user') or {}
    if isinstance(current_user, dict):
        changed_by = (
            current_user.get('name') or
            current_user.get('display_name') or
            current_user.get('preferred_username') or
            current_user.get('email') or
            'Unknown User'
        )
    else:
        changed_by = 'Unknown User'
    return str(changed_by).strip() or 'Unknown User'


def build_spt_submission_payload(form, remaining_fte_capacity):
    spt_value = float(dict(db.get_spt_settings()).get(form['content_type'], 0))
    average_volume = float(form['average_volume']) if form['average_volume'] else 0
    working_minutes = float(form['working_minutes']) if form['working_minutes'] else 1
    fte_requirement = math.ceil(((average_volume * spt_value) / working_minutes) * 100) / 100 if working_minutes else 0
    status = form['status']
    if status == 'Outflow':
        fte_requirement = -fte_requirement
    return {
        'year_endorsed': build_endorsed_date(
            form['year_endorsed'],
            form.get('month_endorsed', ''),
            form.get('day_endorsed', '')
        ),
        'content_type': form['content_type'],
        'fte_requirement': fte_requirement,
        'remaining_fte_capacity': remaining_fte_capacity,
        'frequency': form['frequency'],
        'spt': spt_value,
        'average_volume': form['average_volume'],
        'working_minutes': working_minutes,
        'status': status
    }


def log_spt_row_changes(row_id, old_row, data, changed_by):
    if not old_row:
        return

    new_values = {
        'year_endorsed': data['year_endorsed'],
        'content_type': data['content_type'],
        'fte_requirement': str(data['fte_requirement']),
        'remaining_fte_capacity': str(data['remaining_fte_capacity']),
        'frequency': data['frequency'],
        'spt': str(data['spt']),
        'average_volume': str(data['average_volume']),
        'working_minutes': str(data['working_minutes']),
        'status': data['status']
    }
    old_values = {
        'year_endorsed': old_row[1] or '',
        'content_type': old_row[2] or '',
        'fte_requirement': old_row[3] or '',
        'remaining_fte_capacity': old_row[4] or '',
        'frequency': old_row[5] or '',
        'spt': old_row[6] or '',
        'average_volume': old_row[7] or '',
        'working_minutes': old_row[8] or '',
        'status': old_row[9] or ''
    }
    for field, old_value in old_values.items():
        new_value = new_values[field]
        if str(old_value) != str(new_value):
            db.log_spt_change(row_id, changed_by, field, str(old_value), str(new_value))


def get_settings_view_context(saved=False, **overrides):
    context = {
        'headcount': db.get_headcount(),
        'spt_settings': db.get_spt_settings(),
        'frequency_settings': db.get_frequency_settings(),
        'spt_history': db.get_spt_settings_history(limit=100),
        'saved': saved
    }
    context.update(overrides)
    return context


def get_settings_frequency_values(form):
    return {
        'Daily': form.get('frequency_Daily', ''),
        'Weekly': form.get('frequency_Weekly', ''),
        'Monthly': form.get('frequency_Monthly', '')
    }


def get_settings_row_snapshot(form, index, categories, values, original_categories, original_values):
    cat = categories[index]
    val = values[index] if index < len(values) else ''
    old_cat = original_categories[index].strip() if index < len(original_categories) and original_categories[index] else ''
    old_val = original_values[index].strip() if index < len(original_values) and original_values[index] else ''
    new_cat = cat.strip()
    new_val = val.strip() if val else ''
    row_comment = form.get(f'change_comment_{index}', '')
    return {
        'category': new_cat,
        'value': new_val,
        'old_category': old_cat,
        'old_value': old_val,
        'comment': row_comment,
        'changed': old_cat != new_cat or old_val != new_val,
    }


def append_settings_row_result(index, row_data, settings, changelog_entries, validation_errors, row_comments):
    row_comments[index] = row_data['comment']
    if row_data['category']:
        settings.append((row_data['category'], row_data['value']))
    if not row_data['changed']:
        return

    row_comment = row_data['comment'].strip()
    if not row_comment:
        validation_errors.append(f'Row {index + 1}: Comment is required when changing SPT.')
        return

    changelog_entries.append({
        'category': row_data['category'],
        'old_value': row_data['old_value'],
        'new_value': row_data['value'],
        'comment': row_comment
    })


def parse_settings_submission(form):
    settings = []
    categories = form.getlist('category')
    values = form.getlist('value')
    original_categories = form.getlist('original_category')
    original_values = form.getlist('original_value')
    changelog_entries = []
    validation_errors = []
    row_comments = {}

    for i in range(len(categories)):
        row_data = get_settings_row_snapshot(form, i, categories, values, original_categories, original_values)
        append_settings_row_result(i, row_data, settings, changelog_entries, validation_errors, row_comments)

    return {
        'headcount': form.get('headcount'),
        'settings': settings,
        'frequency_settings': get_settings_frequency_values(form),
        'changelog_entries': changelog_entries,
        'validation_errors': validation_errors,
        'row_comments': row_comments
    }


def apply_settings_submission(submission, changed_by):
    headcount = submission['headcount']
    if headcount:
        db.set_headcount(headcount)
    db.update_spt_settings(submission['settings'])

    for entry in submission['changelog_entries']:
        entry['changed_by'] = changed_by
    db.log_spt_settings_history_entries(submission['changelog_entries'])

    for freq_name, freq_value in submission['frequency_settings'].items():
        if freq_value:
            db.set_frequency_setting(freq_name, freq_value.replace(',', ''))
    update_all_spt_fte_in_db()

def recalculate_fte_for_rows(spt_rows):
    """Recalculate FTE requirements for each row based on current SPT values"""
    updated_rows = []
    for row in spt_rows:
        row_list = list(row)
        # row[6] is SPT, row[7] is average_volume, row[8] is working_minutes
        spt_val = float(row_list[6]) if row_list[6] else 0
        avg_vol = float(row_list[7]) if row_list[7] else 0
        work_min = float(row_list[8]) if row_list[8] else 1
        
        # Recalculate FTE: (Average Volume * SPT) / Working Minutes
        fte = (avg_vol * spt_val) / work_min if work_min else 0
        fte_rounded = math.ceil(fte * 100) / 100
        
        # Apply Outflow negation if needed
        if row_list[9] == 'Outflow':  # row[9] is status
            fte_rounded = -fte_rounded
        
        # Update FTE in row (row[3] is fte_requirement)
        row_list[3] = str(fte_rounded)
        updated_rows.append(tuple(row_list))
    
    return updated_rows

def recalculate_metrics(spt_rows, eff_rows, headcount, year=None):
    """Recalculate metrics based on updated FTE values"""
    def round_up_2(x):
        return math.ceil(float(x) * 100) / 100 if x is not None else 0.00
    
    # Calculate total FTE from recalculated rows
    total_fte = 0
    total_inflow = 0
    total_outflow = 0
    for row in spt_rows:
        fte_val = float(row[3])  # row[3] is recalculated fte_requirement
        total_fte += fte_val
        if row[9] == 'Inflow':  # row[9] is status
            total_inflow += fte_val
        elif row[9] == 'Outflow':
            total_outflow += abs(fte_val)
    
    total_fte = round_up_2(total_fte)
    total_inflow = round_up_2(total_inflow)
    total_outflow = round_up_2(total_outflow)
    
    # Calculate efficiencies total
    eff_total = 0
    gns_eff_total = 0
    entity_eff_total = 0
    for row in eff_rows:
        if not is_active_efficiency_row(row):
            continue
        generated_capacity = parse_numeric_text(row[2] if len(row) > 2 else '')
        eff_total += generated_capacity
        if normalize_efficiency_team(row[10] if len(row) > 10 else '') == 'GNS':
            gns_eff_total += generated_capacity
        else:
            entity_eff_total += generated_capacity
    eff_total = round_up_2(eff_total)
    gns_eff_total = round_up_2(gns_eff_total)
    entity_eff_total = round_up_2(entity_eff_total)
    
    # Under/overstaffing is based on headcount versus SPT FTE only.
    headcount_val = round_up_2(float(headcount) if headcount else 0)
    diff = round_up_2(headcount_val - total_fte)
    
    return {
        'total_fte': f"{total_fte:.2f}",
        'total_inflow': f"{total_inflow:.2f}",
        'total_outflow': f"{total_outflow:.2f}",
        'eff_total': f"{eff_total:.2f}",
        'gns_eff_total': f"{gns_eff_total:.2f}",
        'entity_eff_total': f"{entity_eff_total:.2f}",
        'headcount': f"{headcount_val:.2f}",
        'overstaffed': diff > 0,
        'diff': f"{diff:.2f}"
    }

def compute_content_summary(spt_rows):
    """Build content type FTE summary from already-recalculated SPT rows (consistent with metrics)."""
    summary = {}
    for row in spt_rows:
        ctype = row[2]
        fte = float(row[3]) if row[3] else 0
        summary[ctype] = summary.get(ctype, 0) + fte
    def _ceil2(x):
        return math.ceil(float(x) * 100) / 100
    return [(ctype, f"{_ceil2(fte):.2f}") for ctype, fte in sorted(summary.items())]

def normalize_efficiency_team(team_value):
    team = (team_value or '').strip()
    if not team:
        return 'NBTE'
    if team.lower() == 'entity':
        return 'NBTE'
    return team

def is_active_efficiency_row(row):
    status_value = row[4] if len(row) > 4 and row[4] else ''
    return str(status_value).strip() != 'Discontinued'


def build_efficiency_payload(form, *, current_status='Initiation', current_project_lead='', current_remarks=''):
    return {
        'project_title': form['project_title'],
        'generated_capacity': format_generated_capacity_value(form.get('generated_capacity', '')),
        'project_type': form['project_type'],
        'status': form.get('status', current_status),
        'year': form['year'],
        'project_owner': form.get('project_owner', ''),
        'description': form.get('description', ''),
        'planned_deployment': form.get('planned_deployment', ''),
        'actual_deployment': form.get('actual_deployment', ''),
        'savings': format_savings_value(form.get('savings', '')),
        'team': form.get('team', ''),
        'project_lead': current_project_lead,
        'domestic_reph': form.get('domestic_reph', ''),
        'gptrac': form.get('gptrac', ''),
        'remarks': form.get('remarks', current_remarks),
        'content_process': form.get('content_process', ''),
        'developer': form.get('developer', ''),
        'pbd': form.get('pbd', ''),
        'sbd': form.get('sbd', ''),
        'bu_approved': form.get('bu_approved', ''),
        'uat_from': form.get('uat_from', ''),
        'uat_to': form.get('uat_to', ''),
        'phase_current_end': form.get('phase_current_end', ''),
        'phase_status': form.get('phase_status', 'On Track'),
        'planned_release_date': form.get('planned_release_date', '')
    }


def parse_numeric_text(raw_value):
    try:
        return float(str(raw_value).replace(',', '').replace('$', '').strip()) if raw_value else 0.0
    except ValueError:
        return 0.0


def normalize_efficiency_filter_date(raw_value, fallback_year=''):
    value = (raw_value or '').strip()
    if not value:
        fallback = str(fallback_year or '').strip()
        return f'{fallback}-01-01' if fallback.isdigit() and len(fallback) == 4 else ''
    if len(value) == 10 and value[4] == '-' and value[7] == '-':
        return value
    if len(value) == 7 and value[4] == '-':
        if value[5].upper() == 'Q' and value[6] in '1234':
            quarter_month_map = {'1': '01', '2': '04', '3': '07', '4': '10'}
            return f"{value[:4]}-{quarter_month_map[value[6]]}-01"
        return f'{value}-01'
    if len(value) == 4 and value.isdigit():
        return f'{value}-01-01'
    return ''


def filter_efficiency_rows_for_dashboard(eff_rows, filters):
    if not filters:
        return eff_rows

    selected_year = str(filters.get('year') or '').strip()
    exact_date = str(filters.get('exact_date') or '').strip()
    from_date = str(filters.get('from_date') or '').strip()
    to_date = str(filters.get('to_date') or '').strip()

    filtered_rows = []
    for row in eff_rows:
        row_year = str(row[5] if len(row) > 5 and row[5] else '').strip()
        planned_date = normalize_efficiency_filter_date(row[8] if len(row) > 8 else '', row_year)

        if selected_year and row_year != selected_year:
            continue
        if exact_date and planned_date != exact_date:
            continue
        if from_date and to_date and (not planned_date or planned_date < from_date or planned_date > to_date):
            continue
        filtered_rows.append(row)
    return filtered_rows


def build_efficiency_summary_by_year(eff_rows):
    summary_by_year = {}
    for row in eff_rows:
        if not is_active_efficiency_row(row):
            continue

        year_value = row[5] if len(row) > 5 and row[5] else None
        if not year_value:
            continue

        team_value = normalize_efficiency_team(row[10] if len(row) > 10 else '')
        generated_capacity = parse_numeric_text(row[2] if len(row) > 2 else '')
        savings = parse_numeric_text(row[9] if len(row) > 9 else '')
        year_summary = summary_by_year.setdefault(year_value, {
            'generated_capacity': 0.0,
            'savings': 0.0,
            'gns_generated_capacity': 0.0,
            'nbte_generated_capacity': 0.0,
            'gns_savings': 0.0,
            'nbte_savings': 0.0
        })
        year_summary['generated_capacity'] += generated_capacity
        year_summary['savings'] += savings
        if team_value == 'GNS':
            year_summary['gns_generated_capacity'] += generated_capacity
            year_summary['gns_savings'] += savings
        else:
            year_summary['nbte_generated_capacity'] += generated_capacity
            year_summary['nbte_savings'] += savings

    return sorted(
        [
            (
                year,
                summary['generated_capacity'],
                summary['savings'],
                summary['gns_savings'],
                summary['nbte_savings'],
                summary['gns_generated_capacity'],
                summary['nbte_generated_capacity']
            )
            for year, summary in summary_by_year.items()
        ],
        key=lambda item: item[0]
    )

def format_planned_deployment_display(raw_value):
    value = (raw_value or '').strip()
    if not value:
        return '-'

    year = None
    month = None
    day = None

    if len(value) == 10 and value[4] == '-' and value[7] == '-':
        year = value[0:4]
        month = value[5:7]
        day = value[8:10]
    elif len(value) == 7 and value[4] == '-':
        year = value[0:4]
        month = value[5:7]
        day = '01'
    elif len(value) >= 7 and value[4] == '-' and value[5].upper() == 'Q':
        year = value[0:4]
        quarter_text = value[5:7].upper()
        quarter_month_map = {'Q1': '01', 'Q2': '04', 'Q3': '07', 'Q4': '10'}
        month = quarter_month_map.get(quarter_text)
        day = '01'

    if not year or not month or not day:
        return value

    try:
        month_num = int(month)
        day_num = int(day)
        year_short = year[2:]
        quarter = ((month_num - 1) // 3) + 1
        return f"{month_num}/{day_num}/{year_short} Q{quarter}"
    except ValueError:
        return value

def update_all_spt_fte_in_db():
    """Recalculate and update FTE values for all SPT rows in the database when frequency settings change"""
    # Get all SPT rows
    all_spt_rows = db.conn.execute("""
        SELECT s.id, s.content_type, s.frequency, s.average_volume, s.status,
               COALESCE(ss.value, s.spt) as current_spt
        FROM spt s
        LEFT JOIN spt_settings ss ON s.content_type = ss.category
    """).fetchall()
    
    # Get the latest frequency settings from database (includes defaults)
    frequency_settings = db.get_frequency_settings()
    print(f"[DEBUG] Frequency settings: {frequency_settings}")
    print(f"[DEBUG] SPT rows to update: {len(all_spt_rows)}")
    
    if len(all_spt_rows) == 0:
        print("[DEBUG] No SPT rows to update")
        return
    
    for row in all_spt_rows:
        row_id = row[0]
        content_type = row[1]
        frequency = row[2]  # 'Daily', 'Weekly', 'Monthly'
        avg_vol_str = row[3]
        status = row[4]
        spt_str = row[5]
        
        # Parse values safely
        try:
            avg_vol = float(avg_vol_str) if avg_vol_str else 0
        except:
            avg_vol = 0
            
        try:
            spt_val = float(spt_str) if spt_str else 0
        except:
            spt_val = 0
        
        # Get working minutes from frequency settings
        work_min = float(frequency_settings.get(frequency, '109200'))
        if work_min == 0:
            work_min = 1  # Prevent division by zero
        
        # Calculate FTE: (Average Volume × SPT) / Working Minutes
        fte = (avg_vol * spt_val) / work_min
        fte_rounded = math.ceil(fte * 100) / 100
        
        # Negate for Outflow
        if status == 'Outflow':
            fte_rounded = -fte_rounded
        
        print(f"[DEBUG] Row {row_id} ({content_type}): freq={frequency}, spt={spt_val}, vol={avg_vol}, work_min={work_min} -> FTE={fte_rounded}")
        
        # Update in database
        db.conn.execute("UPDATE spt SET fte_requirement = ?, working_minutes = ? WHERE id = ?", 
                       (str(fte_rounded), str(work_min), row_id))
    
    db.conn.commit()
    print(f"[DEBUG] All FTE values updated successfully")

@main_bp.route('/', methods=['GET'])
@login_required
def dashboard():
    filters = {}
    status = request.args.get('status')
    year = request.args.get('year')
    month = request.args.get('month')
    exact_date = request.args.get('exact_date')
    eff_expanded = request.args.get('eff_expanded') == '1'
    from_date = request.args.get('from_date')
    to_date = request.args.get('to_date')
    if status:
        filters['status'] = status
    if year:
        filters['year'] = year
    if month:
        filters['month'] = month
    if exact_date:
        filters['exact_date'] = exact_date
    if from_date and to_date:
        filters['from_date'] = from_date
        filters['to_date'] = to_date
    spt_rows = db.get_spt(filters)
    # Recalculate FTE requirements with current SPT values
    spt_rows = recalculate_fte_for_rows(spt_rows)
    eff_rows_all = db.get_efficiencies()
    eff_rows = filter_efficiency_rows_for_dashboard(eff_rows_all, filters)
    filtered_eff_ids = [row[0] for row in eff_rows]
    efficiency_summary_by_year = build_efficiency_summary_by_year(eff_rows_all)
    headcount = db.get_headcount()
    # Recalculate metrics based on updated FTE values
    metrics = recalculate_metrics(spt_rows, eff_rows, headcount, year=year)
    content_summary = compute_content_summary(spt_rows)
    message = request.args.get('message')
    years = [row[0] for row in db.get_distinct_years()]
    months = [
        ('01', 'January'), ('02', 'February'), ('03', 'March'), ('04', 'April'),
        ('05', 'May'), ('06', 'June'), ('07', 'July'), ('08', 'August'),
        ('09', 'September'), ('10', 'October'), ('11', 'November'), ('12', 'December')
    ]
    return render_template('dashboard.html', spt_rows=spt_rows, eff_rows=eff_rows, eff_rows_all=eff_rows_all, filtered_eff_ids=filtered_eff_ids, efficiency_summary_by_year=efficiency_summary_by_year, headcount=headcount, metrics=metrics, content_summary=content_summary, message=message, planned_deployment_display=format_planned_deployment_display,
        filter_status=status, filter_year=year, filter_month=month, filter_exact_date=exact_date, filter_from_date=from_date, filter_to_date=to_date, years=years, months=months, eff_expanded=eff_expanded)

@main_bp.route('/add_spt', methods=['GET'])
@login_required
def add_spt():
    categories = [row[0] for row in db.get_spt_settings()]
    category_map = {row[0]: row[1] for row in db.get_spt_settings()}
    metrics = db.get_metrics()
    rem_fte = metrics['diff']
    frequency_settings = db.get_frequency_settings()
    return render_template('add_spt.html', categories=categories, category_map=category_map, rem_fte=rem_fte, frequency_settings=frequency_settings)

@main_bp.route('/add_spt', methods=['POST'])
@login_required
@csrf_protect
def add_spt_submit():
    full_endorsed_date = build_endorsed_date(
        request.form['year_endorsed'],
        request.form.get('month_endorsed', ''),
        request.form.get('day_endorsed', '')
    )

    spt_value = float(dict(db.get_spt_settings()).get(request.form['content_type'], 0))
    average_volume = float(request.form['average_volume']) if request.form['average_volume'] else 0
    working_minutes = float(request.form['working_minutes']) if request.form['working_minutes'] else 1

    # FTE Requirement = (Average Volume * SPT) / Working Minutes
    fte_requirement = math.ceil(((average_volume * spt_value) / working_minutes) * 100) / 100 if working_minutes else 0

    status = request.form['status']

    # For Outflow, negate the FTE requirement so it adds to the overstaffed/understaffed metric
    if status == 'Outflow':
        fte_requirement = -fte_requirement

    data = {
        'year_endorsed': full_endorsed_date,
        'content_type': request.form['content_type'],
        'fte_requirement': fte_requirement,
        'remaining_fte_capacity': db.get_metrics()['diff'],
        'frequency': request.form['frequency'],
        'spt': spt_value,
        'average_volume': request.form['average_volume'],
        'working_minutes': request.form['working_minutes'],
        'status': status
    }
    db.add_spt(data)
    return render_template('close_modal.html')

@main_bp.route('/edit_spt/<int:row_id>', methods=['GET'])
@login_required
@requires_role('Manager')
def edit_spt(row_id):
    row = db.conn.execute("SELECT * FROM spt WHERE id=?", (row_id,)).fetchone()
    categories = [row[0] for row in db.get_spt_settings()]
    category_map = {row[0]: row[1] for row in db.get_spt_settings()}
    metrics = db.get_metrics()
    rem_fte = metrics['diff']
    frequency_settings = db.get_frequency_settings()
    return render_template('edit_spt.html', row=row, categories=categories, category_map=category_map, rem_fte=rem_fte, frequency_settings=frequency_settings)

@main_bp.route('/edit_spt/<int:row_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def edit_spt_submit(row_id):
    old_row = db.conn.execute("SELECT * FROM spt WHERE id=?", (row_id,)).fetchone()
    data = build_spt_submission_payload(request.form, db.get_metrics()['diff'])
    changed_by = get_effective_user_name()
    log_spt_row_changes(row_id, old_row, data, changed_by)
    db.update_spt(row_id, data)
    return render_template('close_modal.html')

@main_bp.route('/delete_spt/<int:row_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def delete_spt(row_id):
    db.delete_spt(row_id)
    return redirect(url_for('main.dashboard'))

@main_bp.route('/add_efficiency', methods=['GET'])
@login_required
def add_efficiency():
    return render_template('add_efficiency.html')

@main_bp.route('/add_efficiency', methods=['POST'])
@login_required
@csrf_protect
def add_efficiency_submit():
    data = build_efficiency_payload(request.form, current_status='Initiation')
    db.add_efficiency(data)
    return render_template('close_modal.html')

@main_bp.route('/edit_efficiency/<int:row_id>', methods=['GET'])
@login_required
@requires_role('Manager')
def edit_efficiency(row_id):
    standalone = request.args.get('standalone') == '1'
    standalone_view = request.args.get('eff_view', 'details')
    row = db.conn.execute("SELECT * FROM efficiencies WHERE id=?", (row_id,)).fetchone()
    return render_template('edit_efficiency.html', row=row, standalone=standalone, standalone_view=standalone_view)

@main_bp.route('/edit_efficiency/<int:row_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def edit_efficiency_submit(row_id):
    standalone = request.args.get('standalone') == '1'
    standalone_view = request.args.get('eff_view', 'details')
    current_row = db.conn.execute("SELECT * FROM efficiencies WHERE id=?", (row_id,)).fetchone()
    current_status = current_row[4] if current_row and len(current_row) > 4 else 'N/A'
    current_project_lead = current_row[11] if current_row and len(current_row) > 11 else ''
    current_remarks = current_row[14] if current_row and len(current_row) > 14 else ''

    data = build_efficiency_payload(
        request.form,
        current_status=current_status,
        current_project_lead=current_project_lead,
        current_remarks=current_remarks,
    )
    db.update_efficiency(row_id, data)
    if standalone:
        return redirect(url_for('main.dashboard', message='Efficiency updated successfully.', eff_expanded='1', eff_view=standalone_view))
    return render_template('close_modal.html')

@main_bp.route('/delete_efficiency/<int:row_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def delete_efficiency(row_id):
    db.delete_efficiency(row_id)
    return redirect(url_for('main.dashboard'))

@main_bp.route('/update_efficiency_remarks/<int:row_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def update_efficiency_remarks(row_id):
    remarks = request.form.get('remarks', '')
    db.update_efficiency_remarks(row_id, remarks)
    return ('', 204)

@main_bp.route('/settings', methods=['GET'])
@login_required
@requires_role('Manager')
def settings():
    saved = request.args.get('saved') == '1'
    return render_template('settings.html', **get_settings_view_context(saved=saved))

@main_bp.route('/settings', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def settings_submit():
    submission = parse_settings_submission(request.form)
    if submission['validation_errors']:
        return render_template(
            'settings.html',
            **get_settings_view_context(
                saved=False,
                headcount=submission['headcount'],
                spt_settings=submission['settings'],
                frequency_settings=submission['frequency_settings'],
                error_message=' '.join(submission['validation_errors']),
                row_comments=submission['row_comments'],
            )
        )

    apply_settings_submission(submission, get_effective_user_name())
    return redirect(url_for('main.settings', saved='1'))

@main_bp.route('/add_spt_category', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def add_spt_category():
    category = request.form['category']
    db.add_spt_category(category)
    return redirect(url_for('main.settings'))

@main_bp.route('/delete_spt_category/<category>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def delete_spt_category(category):
    db.delete_spt_category(category)
    return redirect(url_for('main.settings'))

@main_bp.route('/delete_spt_history/<int:history_id>', methods=['POST'])
@login_required
@requires_role('Manager')
@csrf_protect
def delete_spt_history(history_id):
    db.delete_spt_settings_history_entry(history_id)
    return redirect(url_for('main.settings'))
