import json
from pathlib import Path
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import Account, Category, Transaction
from app.services.finance import (
    FinanceError,
    amount_input_value,
    category_display_name,
    create_category,
    create_transaction,
    create_transfer,
    delete_transaction,
    find_transaction,
    format_minor_amount,
    list_categories,
    query_transactions,
    set_category_archived,
    update_transaction,
    update_category,
)
from .forms import CategoryForm, TransactionFilterForm, TransactionForm, TransferForm

transactions_bp = Blueprint("transactions", __name__)
ALLOWED_UPLOAD_EXTENSIONS = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
    ".pdf": "pdf",
}


def _store_attachment(file_storage) -> str | None:
    if not file_storage or not file_storage.filename:
        return None
    safe_name = secure_filename(file_storage.filename)
    extension = Path(safe_name).suffix.lower()
    expected = ALLOWED_UPLOAD_EXTENSIONS.get(extension)
    if expected is None:
        raise FinanceError(_("Type de reçu non autorisé."))
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    signatures = {
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "pdf": header.startswith(b"%PDF-"),
    }
    if not signatures[expected]:
        raise FinanceError(_("Le contenu du reçu ne correspond pas au type de fichier annoncé."))
    filename = f"{uuid4().hex}{extension}"
    relative_path = Path(str(current_user.id)) / filename
    directory = Path(current_app.config["UPLOAD_FOLDER"]) / str(current_user.id)
    directory.mkdir(parents=True, exist_ok=True)
    file_storage.save(directory / filename)
    return relative_path.as_posix()


def _remove_attachment(relative_path: str | None) -> None:
    if not relative_path:
        return
    root = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    target = (root / relative_path).resolve()
    if target.is_relative_to(root) and target.is_file():
        target.unlink()


def _htmx_form_error(errors: list[str], target: str = "#transaction-feedback"):
    response = current_app.make_response(
        render_template("transactions/_form_errors.html", errors=errors)
    )
    response.headers["HX-Retarget"] = target
    response.headers["HX-Reswap"] = "innerHTML"
    return response


def _render_list(*, error: str | None = None, status: int = 200):
    form = TransactionFilterForm(current_user.id, formdata=request.args)
    account_id = form.account_id.data or None
    category_id = form.category_id.data or None
    if request.args and not form.validate():
        errors = [message for messages in form.errors.values() for message in messages]
        page = query_transactions(current_user.id)
        error = error or " ".join(errors)
    else:
        try:
            page = query_transactions(
                current_user.id,
                search=form.search.data,
                account_id=account_id,
                transaction_type=form.type.data or None,
                category_id=category_id,
                date_from=form.date_from.data,
                date_to=form.date_to.data,
                min_amount=form.min_amount.data,
                max_amount=form.max_amount.data,
                page=request.args.get("page", 1, type=int),
            )
        except FinanceError as exception:
            page = query_transactions(current_user.id)
            error = str(exception)

    accounts = Account.query.filter_by(user_id=current_user.id).order_by(Account.name).all()
    categories = list_categories(current_user.id)
    transfer_form = TransferForm(current_user.id)
    transaction_form = TransactionForm(
        current_user.id, category_type=request.form.get("type")
    )
    balances = {
        transaction.id: format_minor_amount(transaction.amount, transaction.currency_code)
        for transaction in page.items
    }
    filter_args = request.args.to_dict()
    filter_args.pop("page", None)
    response = render_template(
        "transactions/list.html",
        page=page,
        filter_form=form,
        transaction_form=transaction_form,
        transfer_form=transfer_form,
        accounts=accounts,
        categories=categories,
        balances=balances,
        category_display_name=category_display_name,
        error=error,
        filter_args=filter_args,
    )
    return response, status


@transactions_bp.route("/")
@login_required
def list_transactions():
    return _render_list()


@transactions_bp.get("/category-options")
@login_required
def category_options():
    form = TransactionForm(
        current_user.id, category_type=request.args.get("type")
    )
    return render_template("transactions/_category_select.html", field=form.category_id)


@transactions_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_transaction():
    form = TransactionForm(
        current_user.id, category_type=request.form.get("type")
    )
    if form.validate_on_submit():
        stored_path = None
        try:
            stored_path = _store_attachment(form.attachment.data)
            transaction = create_transaction(
                current_user,
                form.account_id.data,
                form.type.data,
                form.amount.data,
                form.category_id.data or None,
                form.occurred_on.data,
                form.note.data or "",
                form.tags.data or "",
                stored_path,
            )
        except FinanceError as error:
            db.session.rollback()
            _remove_attachment(stored_path)
            if request.headers.get("HX-Request") == "true":
                return _htmx_form_error([str(error)])
            flash(str(error), "error")
        else:
            if request.headers.get("HX-Request") == "true":
                return render_template(
                    "transactions/_item.html",
                    transaction=transaction,
                    amount=format_minor_amount(
                        transaction.amount, transaction.currency_code
                    ),
                    category_name=category_display_name(transaction.category)
                    if transaction.category
                    else None,
                )
            flash(_("La transaction a été ajoutée."), "success")
            return redirect(url_for("transactions.list_transactions"))
    if request.headers.get("HX-Request") == "true":
        return _htmx_form_error(
            [message for messages in form.errors.values() for message in messages]
        )
    return render_template(
        "transactions/new.html",
        form=form,
        category_display_name=category_display_name,
    )


@transactions_bp.route("/transfer", methods=["POST"])
@login_required
def transfer():
    form = TransferForm(current_user.id)
    if form.validate_on_submit():
        try:
            outgoing, incoming = create_transfer(
                current_user,
                form.source_account_id.data,
                form.destination_account_id.data,
                form.source_amount.data,
                form.occurred_on.data,
                form.note.data or "",
                form.tags.data or "",
            )
        except FinanceError as error:
            db.session.rollback()
            if request.headers.get("HX-Request") == "true":
                return _htmx_form_error([str(error)], "#transfer-feedback")
            flash(str(error), "error")
        else:
            if request.headers.get("HX-Request") == "true":
                return render_template(
                    "transactions/_transfer_items.html",
                    outgoing=outgoing,
                    incoming=incoming,
                    outgoing_amount=format_minor_amount(
                        outgoing.amount, outgoing.currency_code
                    ),
                    incoming_amount=format_minor_amount(
                        incoming.amount, incoming.currency_code
                    ),
                )
            flash(_("Le virement a été enregistré."), "success")
            return redirect(url_for("transactions.list_transactions"))
    else:
        if request.headers.get("HX-Request") == "true":
            return _htmx_form_error(
                [
                    str(error)
                    for errors in form.errors.values()
                    for error in errors
                ],
                "#transfer-feedback",
            )
        flash(_("Vérifiez les champs du virement."), "error")
    return redirect(url_for("transactions.list_transactions"))


@transactions_bp.route("/<int:transaction_id>/edit", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id: int):
    transaction = Transaction.query.filter_by(
        id=transaction_id, user_id=current_user.id
    ).first_or_404()
    if transaction.transfer_group_id:
        abort(400, description=_("Un virement ne peut pas être modifié séparément."))
    is_htmx = request.headers.get("HX-Request") == "true"
    form = TransactionForm(
        current_user.id,
        include_archived_account_id=transaction.account_id,
        category_type=request.form.get("type") or transaction.type,
    )
    if not form.is_submitted():
        form.account_id.data = transaction.account_id
        form.type.data = transaction.type
        form.amount.data = amount_input_value(transaction.amount, transaction.currency_code)
        form.category_id.data = transaction.category_id or 0
        form.occurred_on.data = transaction.date.date()
        form.note.data = transaction.note
        form.tags.data = transaction.tags
    if is_htmx and request.method == "GET":
        return render_template(
            "transactions/_edit_form.html",
            form=form,
            transaction=transaction,
        )
    if form.validate_on_submit():
        new_path = None
        old_path = transaction.attachment_path
        try:
            new_path = _store_attachment(form.attachment.data)
            update_transaction(
                current_user,
                transaction.id,
                form.account_id.data,
                form.type.data,
                form.amount.data,
                form.category_id.data or None,
                form.occurred_on.data,
                form.note.data or "",
                form.tags.data or "",
                new_path,
            )
        except FinanceError as error:
            db.session.rollback()
            _remove_attachment(new_path)
            if is_htmx:
                form.amount.errors.append(str(error))
                return render_template(
                    "transactions/_edit_form.html",
                    form=form,
                    transaction=transaction,
                )
            flash(str(error), "error")
        else:
            if new_path:
                _remove_attachment(old_path)
            if is_htmx:
                return render_template(
                    "transactions/_item.html",
                    transaction=transaction,
                    amount=format_minor_amount(
                        transaction.amount, transaction.currency_code
                    ),
                    category_name=category_display_name(transaction.category)
                    if transaction.category
                    else None,
                )
            flash(_("La transaction a été mise à jour."), "success")
            return redirect(url_for("transactions.list_transactions"))
    if is_htmx:
        return render_template(
            "transactions/_edit_form.html",
            form=form,
            transaction=transaction,
        )
    return render_template(
        "transactions/edit.html",
        form=form,
        transaction=transaction,
        category_display_name=category_display_name,
    )


@transactions_bp.post("/<int:transaction_id>/delete")
@login_required
def remove_transaction(transaction_id: int):
    transaction = find_transaction(current_user.id, transaction_id)
    if transaction is None:
        abort(404)
    old_path = transaction.attachment_path
    transfer_group_id = transaction.transfer_group_id
    paired_paths = []
    paired_ids = [transaction.id]
    if transfer_group_id:
        paired_paths = [
            row.attachment_path
            for row in Transaction.query.filter_by(
                user_id=current_user.id, transfer_group_id=transfer_group_id
            )
        ]
        paired_ids = [
            row.id
            for row in Transaction.query.filter_by(
                user_id=current_user.id, transfer_group_id=transfer_group_id
            )
        ]
    delete_error = None
    try:
        delete_transaction(current_user.id, transaction.id)
    except FinanceError as error:
        db.session.rollback()
        delete_error = str(error)
        flash(str(error), "error")
    else:
        _remove_attachment(old_path)
        for attachment_path in paired_paths:
            if attachment_path != old_path:
                _remove_attachment(attachment_path)
        flash(_("La transaction a été supprimée."), "success")
    if request.headers.get("HX-Request") == "true":
        if delete_error:
            transaction = find_transaction(current_user.id, transaction_id)
            if transaction is None:
                return ""
            return render_template(
                "transactions/_item.html",
                transaction=transaction,
                amount=format_minor_amount(
                    transaction.amount, transaction.currency_code
                ),
                category_name=category_display_name(transaction.category)
                if transaction.category
                else None,
                inline_error=delete_error,
            )
        if transfer_group_id:
            response = current_app.response_class("")
            response.headers["HX-Trigger-After-Swap"] = json.dumps(
                {"caurisTransferDeleted": {"ids": paired_ids}}
            )
            return response
        return ""
    return redirect(url_for("transactions.list_transactions"))


@transactions_bp.get("/attachment/<int:transaction_id>")
@login_required
def download_attachment(transaction_id: int):
    transaction = find_transaction(current_user.id, transaction_id)
    if transaction is None or not transaction.attachment_path:
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_FOLDER"],
        transaction.attachment_path,
        as_attachment=True,
    )


@transactions_bp.route("/categories", methods=["GET", "POST"])
@login_required
def categories():
    form = CategoryForm(current_user.id)
    if form.validate_on_submit():
        try:
            create_category(
                current_user.id,
                form.key.data,
                form.custom_name.data,
                form.type.data,
                form.parent_id.data or None,
                form.icon.data or "",
                form.color.data or "",
            )
        except FinanceError as error:
            db.session.rollback()
            flash(str(error), "error")
        else:
            flash(_("La catégorie a été créée."), "success")
            return redirect(url_for("transactions.categories"))
    return render_template(
        "transactions/categories.html",
        form=form,
        categories=list_categories(current_user.id, include_archived=True),
        category_display_name=category_display_name,
        edit_category=None,
    )


@transactions_bp.route("/categories/<int:category_id>/edit", methods=["GET", "POST"])
@login_required
def edit_category(category_id: int):
    category = Category.query.filter_by(
        id=category_id, user_id=current_user.id
    ).first_or_404()
    form = CategoryForm(current_user.id)
    if not form.is_submitted():
        form.key.data = category.key
        form.custom_name.data = category.custom_name
        form.type.data = category.type
        form.parent_id.data = category.parent_id or 0
        form.icon.data = category.icon
        form.color.data = category.color
    if form.validate_on_submit():
        try:
            update_category(
                current_user.id,
                category.id,
                form.custom_name.data,
                form.type.data,
                form.parent_id.data or None,
                form.icon.data or "",
                form.color.data or "",
            )
        except FinanceError as error:
            db.session.rollback()
            flash(str(error), "error")
        else:
            flash(_("La catégorie a été mise à jour."), "success")
            return redirect(url_for("transactions.categories"))
    return render_template(
        "transactions/categories.html",
        form=form,
        categories=list_categories(current_user.id, include_archived=True),
        category_display_name=category_display_name,
        edit_category=category,
    )


@transactions_bp.post("/categories/<int:category_id>/archive")
@login_required
def archive_category(category_id: int):
    try:
        set_category_archived(current_user.id, category_id, True)
    except FinanceError:
        abort(404)
    flash(_("La catégorie a été archivée."), "success")
    return redirect(url_for("transactions.categories"))


@transactions_bp.post("/categories/<int:category_id>/restore")
@login_required
def restore_category(category_id: int):
    try:
        set_category_archived(current_user.id, category_id, False)
    except FinanceError:
        abort(404)
    flash(_("La catégorie a été restaurée."), "success")
    return redirect(url_for("transactions.categories"))
