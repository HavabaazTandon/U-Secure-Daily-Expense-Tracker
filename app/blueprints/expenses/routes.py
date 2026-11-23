"""Expense CRUD and the transactions page."""
from datetime import date

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ...forms import DeleteForm, ExpenseForm
from ...services import expense_service as svc
from ...utils import is_safe_redirect_target

bp = Blueprint("expenses", __name__, url_prefix="/expenses")


def _next_url(default: str) -> str:
    target = request.args.get("next") or request.form.get("next")
    return target if is_safe_redirect_target(target) else default


@bp.route("/")
@login_required
def index():
    filters = svc.ExpenseFilters.from_args(request.args)
    pagination = svc.paginate(current_user.id, filters, current_app.config["EXPENSES_PER_PAGE"])
    total = svc.filtered_total(current_user.id, filters)
    return render_template(
        "expenses/index.html",
        filters=filters,
        pagination=pagination,
        total=total,
        sort_options=svc.SORT_OPTIONS,
        current_url=request.full_path.rstrip("?"),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    form = ExpenseForm()
    if request.method == "GET":
        form.expense_date.data = date.today()
    if form.validate_on_submit():
        svc.create_expense(
            current_user.id, form.category.data, form.amount.data, form.expense_date.data, form.description.data
        )
        flash("Expense added.", "success")
        return redirect(url_for("expenses.index"))
    return render_template("expenses/form.html", form=form, mode="new", expense=None), (400 if form.errors else 200)


@bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit(expense_id: int):
    expense = svc.get_owned_expense_or_404(expense_id, current_user.id)
    form = ExpenseForm(obj=expense) if request.method == "GET" else ExpenseForm()
    back = _next_url(url_for("expenses.index"))
    if form.validate_on_submit():
        svc.update_expense(
            expense, form.category.data, form.amount.data, form.expense_date.data, form.description.data
        )
        flash("Expense updated.", "success")
        return redirect(back)
    return (
        render_template("expenses/form.html", form=form, mode="edit", expense=expense, next_url=back),
        (400 if form.errors else 200),
    )


@bp.route("/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete(expense_id: int):
    expense = svc.get_owned_expense_or_404(expense_id, current_user.id)
    form = DeleteForm()
    if form.validate_on_submit():
        svc.delete_expense(expense)
        flash("Expense deleted.", "success")
    else:
        flash("Could not delete the expense. Please try again.", "error")
    return redirect(_next_url(url_for("expenses.index")))
