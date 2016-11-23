# -*- coding: utf-8 -*-
from datetime import datetime
import os
import shutil

from annoying.decorators import render_to
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
from django.views.generic.edit import FormView
from django.contrib.contenttypes.models import ContentType

from gsi.models import (Run, RunBase, RunStep, Log, OrderedCardItem, HomeVariables, VariablesGroup, YearGroup, Year,
                        Satellite, InputDataDirectory, SubCardItem, Resolution, Tile)
from cards.card_update_create import (qrf_update_create, rfscore_update_create, remap_update_create,
                        year_filter_update_create, collate_update_create, preproc_update_create, mergecsv_update_create,
                        rftrain_update_create, randomforest_update_create, calcstats_update_create)
from cards.cards_forms import (QRFForm, RFScoreForm, RemapForm, YearFilterForm, CollateForm, PreProcForm, MergeCSVForm,
                                RFTrainForm, RandomForestForm, CalcStatsForm)
from gsi.gsi_items_update_create import (configfile_update_create, var_group_update_create, area_update_create,
                                        yg_update_create, create_update_card_sequence, satellite_update_create,
                                        data_dir_update_create, resolution_update_create, tile_update_create,
                                        year_update_create)
from gsi.gsi_forms import (RunForm, CardSequenceForm, CardSequenceCardForm, CardSequenceCreateForm, HomeVariablesForm,
                            EnvironmentGroupsForm, AreasForm, YearGroupForm, SatelliteForm, UploadFileForm,
                            InputDataDirectoryForm, ConfigFileForm, ResolutionForm, TileForm, YearForm)
from core.utils import (make_run, get_dir_root_static_path,
                        get_path_folder_run, slash_remove_from_path,
                        get_files_dirs, create_sub_dir, get_copy_name,
                        get_files, get_card_model)
from core.get_post import get_post
from core.copy_card import create_copycard
from log.logger import get_logs
from gsi.settings import (PATH_RUNS_SCRIPTS, CONFIGFILE_PATH, GOOGLE_MAP_ZOOM)
from core.paginations import paginations

TITLES = {
    'home': ['Home', 'index'],
    'setup_run': ['GSI Run Setup', 'run_setup'],
    'edit_run': ['GSI Edit Run', 'run_update'],
    'new_run': ['GSI New Run', 'new_run'],
    'card_sequence': ['GSI Card Sequence', 'card_sequence'],
    'add_card_sequence': ['GSI New Card Sequence', 'new_card_sequence'],
    'card_item_update': ['GSI Card Item', 'card_item_update'],
}


def handle_uploaded_file(f, path):
    with open(path, 'a') as destination:
        for chunk in f.chunks():
            destination.write(chunk)


def update_qrf_rftrain_card(cs, cs_cards):
    from cards.models import QRF, RFTrain

    configfile = cs.configfile
    qrf_directory = str(configfile).split('.cfg')[0]
    rftrain_configfile = '{0}{1}'.format(CONFIGFILE_PATH, configfile)

    for n in cs_cards:
        card_model = n.card_item.content_type.model

        if card_model == 'qrf':
            data_card = QRF.objects.get(name=n.card_item.content_object)
            data_card.directory = qrf_directory
            data_card.save()
        elif card_model == 'rftrain':
            data_card = RFTrain.objects.get(name=n.card_item.content_object)
            data_card.config_file = rftrain_configfile
            data_card.save()


@render_to('gsi/blocking.html')
def blocking(request):
    data = {}
    return data


class UploadStaticDataView(FormView):
    success_url = 'index.html'
    form_class = UploadFileForm
    template_name = 'gsi/upload_file.html'

    def get_context_data(self, **kwargs):
        context = super(UploadStaticDataView, self).get_context_data(**kwargs)
        title = 'Upload Test Data'
        url_name = 'upload_file'
        context.update({
            'title': title,
            'url_name': url_name,
        })

        return context

    def form_valid(self, form):
        home_var = HomeVariables.objects.all()[0]
        file_name = str(self.request.FILES['test_data']).decode('utf-8')
        path_test_data = os.path.join(home_var.RF_AUXDATA_DIR, file_name)
        # type_file = str(request.FILES['test_data'].content_type).split('/')[0]
        handle_uploaded_file(self.request.FILES['test_data'], path_test_data)
        message = u'Test data "{0}" is loaded'.format(file_name)

        return HttpResponseRedirect('%s?status_message=%s' %
                                    (reverse('index'), message))


def write_card_to_cs(card_sequence, query):
    dict_carditem_order = {}
    carditem_select = query.getlist('carditem_select')
    carditem_order = query.getlist('carditem_order')
    num_card = len(carditem_select)

    for n in xrange(num_card):
        card_item = get_object_or_404(CardItem, pk=int(carditem_select[n]))

        CardSequence.cards.through.objects.create(
            sequence=card_sequence,
            card_item=card_item,
            order=int(carditem_order[n]), )


def create_new_runbase(request, name):
    new_rb = None
    rb = get_object_or_404(RunBase, name=name)
    rb_count = RunBase.objects.all().count()
    copy_name_rb = get_copy_name(name)
    new_name_rb = '{0}*cp{1}'.format(copy_name_rb, rb_count)

    if RunBase.objects.filter(name=new_name_rb).exists():
        try:
            new_name_rb = '{0}_{1}'.format(new_name_rb, 1)
        except ValueError:
            num = int(rb_count) + 1
            new_name_rb = '{0}*cp{1}'.format(new_name_rb, num)
        # except TypeError:
        # 	num_name = int(name_list[2:][0]) + 1
        # 	new_name_rb = '{0}*cp{1}'.format(name, num_name)

    try:
        new_rb = RunBase.objects.create(
            name=new_name_rb,
            author=request.user,
            description=rb.description,
            purpose=rb.purpose,
            directory_path=rb.directory_path,
            resolution=rb.resolution, )
        new_rb_cs = get_object_or_404(CardSequence, pk=new_rb.card_sequence.id)

        new_rb_cs.environment_base = rb.card_sequence.environment_base
        new_rb_cs.environment_override = rb.card_sequence.environment_override
        new_rb_cs.save()

        new_rb_cs_cards = CardSequence.cards.through.objects.filter(
            sequence_id=new_rb_cs.id)
        card_sequence = CardSequence.objects.get(id=new_rb_cs.id)
        copy_rb_cs_cards = CardSequence.cards.through.objects.filter(
            sequence_id=rb.card_sequence.id)

        for n in copy_rb_cs_cards:
            card_model = n.card_item.content_type.model
            new_copy_card = create_copycard(str(n.card_item), card_model)
            content_type = get_object_or_404(
                ContentType, app_label='cards', model=card_model)
            card_item = get_object_or_404(
                CardItem,
                content_type=content_type,
                object_id=new_copy_card.id)

            # print 'new_copy_card ============================= ', new_copy_card
            # name_ci = str(n.card_item)
            # new_name_ci = '{0}*cp{1}'.format(name_ci, rb_count)
            # print 'NAME content_type ============= ', str(n.card_item)
            # print 'NAME NEW content_type ============= ', new_name_ci
            # print 'content_type ============= ', n.card_item.content_type.model

            # new_card_item = n.card_item
            CardSequence.cards.through.objects.create(
                sequence=card_sequence,
                card_item=card_item,
                order=n.order, )
    except Exception, e:
        print 'ERROR create_new_runbase ============== ', e

    return new_rb


def get_number_cards(rb, user):
    num_card = 0
    # run = get_object_or_404(Run, run_base=rb, user=user)
    all_card = OrderedCardItem.objects.filter(sequence__runbase=rb.run_base)

    for card in all_card:
        if card.run_parallel:
            num_card += card.number_sub_cards
        else:
            num_card += 1

    return num_card


# upload_static_data_view = user_passes_test(login_url='/', redirect_field_name='')(UploadStaticDataView.as_view())


@user_passes_test(lambda u: u.is_superuser)
@render_to('gsi/upload_file.html')
def upload_file(request):
    title = 'Upload Test Data'
    url_name = 'upload_file'

    try:
        home_var = HomeVariables.objects.all()[0]
    except IndexError:
        home_var = ''

    if request.POST:
        form = UploadFileForm(request.POST, request.FILES)

        if form.is_valid():
            if home_var:
                file_name = str(request.FILES['test_data']).decode('utf-8')
                path_test_data = os.path.join(home_var.RF_AUXDATA_DIR,
                                              file_name)
                handle_uploaded_file(request.FILES['test_data'],
                                     path_test_data)

                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('upload_file'),
                    (u'Test data "{0}" is loaded'.format(file_name))))

                # type_file = str(request.FILES['test_data'].content_type).split('/')[0]
                # if type_file != 'image':
                # 	handle_uploaded_file(request.FILES['test_data'], path_test_data)
                # 	return HttpResponseRedirect(
                # 			u'%s?status_message=%s' % (reverse('index'),
                # 			(u'Test data "{0}" is loaded'.format(file_name)))
                # 	)
                # else:
                # 	return HttpResponseRedirect(
                # 			u'%s?status_message=%s' % (reverse('index'),
                # 			(u'The file "{0}" can not be loaded. \
                # 			To download using a text file format'.format(file_name)))
                # 	)
            else:
                return HttpResponseRedirect(u'%s?danger_message=%s' % (
                    reverse('index'), (u'Please fill the Home Variables.')))
        else:
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse('upload_file'), (u'Sorry. Upload error: {0}'.format(
                    form['test_data'].errors.as_text()))))
    else:
        form = UploadFileForm()
    data = {'title': title, 'form': form, 'url_name': url_name}

    return data


@login_required
@render_to('gsi/index.html')
def index(request):
    title = 'Main Menu'
    url_name = 'home'
    is_homevar = False

    try:
        home_var = HomeVariables.objects.all()[0]
        if home_var.RF_AUXDATA_DIR:
            is_homevar = True
    except IndexError:
        home_var = ''

    if request.POST:
        form = UploadFileForm(request.POST, request.FILES)

        if form.is_valid():
            if home_var:
                file_name = str(request.FILES['test_data']).decode('utf-8')
                path_test_data = os.path.join(home_var.RF_AUXDATA_DIR,
                                              file_name)
                # type_file = str(request.FILES['test_data'].content_type).split('/')[0]
                handle_uploaded_file(request.FILES['test_data'],
                                     path_test_data)

                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('index'),
                    (u'Test data "{0}" is loaded'.format(file_name))))
            else:
                return HttpResponseRedirect(u'%s?danger_message=%s' % (
                    reverse('index'), (u'Please fill the Home Variables.')))
        else:
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse('index'), (u'Upload error: {0}'.format(form[
                    'test_data'].errors.as_text()))))
    else:
        form = UploadFileForm()
    data = {'title': title, 'form': form, 'url_name': url_name, 'is_homevar': is_homevar}

    return data


@login_required
@render_to('gsi/run_setup.html')
def run_setup(request):
    title = 'Run Setup'
    run_bases = RunBase.objects.all().order_by('-date_modified')
    run_name = ''
    url_name = 'run_setup'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')
        if order_by in ('name', 'author', 'date_created', 'date_modified'):
            run_bases = run_bases.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                run_bases = run_bases.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(RunBase, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)

        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(RunBase, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        data_post = request.POST

        if data_post.get('copy_btn'):
            run_bases_current = get_object_or_404(
                RunBase, pk=data_post.get('copy_btn'))
            run_name += '"' + run_bases_current.name + '"'
            new_rb = create_new_runbase(request, run_bases_current.name)

            return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                'run_setup'
            ), (u'Run the {0} has been successfully copied. Creates a copy of the "{1}".'.
                format(run_name, new_rb.name))))
        elif data_post.get('run_select') and not data_post.get('copy_btn'):
            for run_id in data_post.getlist('run_select'):
                cur_run = get_object_or_404(RunBase, pk=run_id)
                run_name += '"' + cur_run.name + '", '
                rb_cs = get_object_or_404(
                    CardSequence, id=cur_run.card_sequence.id)
                cur_run.delete()
                rb_cs.delete()
            run_name = run_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('run_setup'),
                (u'Run(s): {0} ==> deleted.'.format(run_name))))
        elif data_post.get('delete_button'):
            run_bases_current = get_object_or_404(
                RunBase, pk=data_post.get('delete_button'))
            run_name += '"' + run_bases_current.name + '"'
            rb_cs = get_object_or_404(
                CardSequence, id=run_bases_current.card_sequence.id)
            run_bases_current.delete()
            rb_cs.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('run_setup'),
                (u'Run: {0} ==> deleted.'.format(run_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('run_setup'),
                (u"To delete, select Run or more Runs.")))

    # paginations
    model_name = paginations(request, run_bases)

    data = {
        'title': title,
        'run_bases': model_name,
        'model_name': model_name,
        'url_name': url_name,
    }

    return data


@login_required
@render_to('gsi/new_run.html')
def new_run(request):
    title = 'New Run'
    form = None
    cards_item = CardItem.objects.all()

    if request.method == "POST":
        form = RunForm(request.POST)

        if form.is_valid():
            if not RunBase.objects.filter(
                    name=form.cleaned_data["name"]).exists():
                new_run_base = RunBase.objects.create(
                    name=form.cleaned_data["name"],
                    description=form.cleaned_data["description"],
                    purpose=form.cleaned_data["purpose"],
                    # card_sequence=form.cleaned_data["card_sequence"],
                    directory_path=form.cleaned_data["directory_path"],
                    resolution=form.cleaned_data["resolution"],
                    author=request.user, )

                path_dir = os.path.join(
                    str(new_run_base.resolution),
                    str(new_run_base.directory_path))
                create_sub_dir(path_dir)
                card_sequence = new_run_base.card_sequence

                if request.POST.get('save_button') is not None:
                    if request.POST.get('carditem_select'):
                        write_card_to_cs(card_sequence, request.POST)

                    return HttpResponseRedirect(u'%s?status_message=%s' % (
                        reverse('run_setup'), (
                            u"RunID {0} created successfully".format(
                                new_run_base.id))))
                if request.POST.get('save_update_button') is not None:
                    if request.POST.get('carditem_select'):
                        write_card_to_cs(card_sequence, request.POST)
                    return HttpResponseRedirect(u'%s?status_message=%s' % (
                        reverse(
                            'run_update', args=[new_run_base.id]),
                        (u"RunID {0} created successfully. You may edit it again below.".
                         format(new_run_base.id))))
            else:
                return HttpResponseRedirect(u'%s?warning_message=%s' % (
                    reverse('new_run'), (
                        u'Run with the name "{0}" already exists.'.format(
                            form.cleaned_data["name"]))))
    else:
        form = RunForm()

    data = {'title': title, 'form': form, 'cards_item': cards_item}

    return data


@login_required
@render_to('gsi/run_update.html')
def run_update(request, run_id):
    run_base = get_object_or_404(RunBase, pk=run_id)
    title = 'Edit "{0}"'.format(run_base.name)
    form = None
    cur_run = None

    if request.method == "POST":
        form = RunForm(request.POST)

        if request.POST.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' % (
                reverse('run_setup'),
                (u"Run {0} updated canceled".format(run_base.name))))
        else:
            if form.is_valid():
                if RunBase.objects.filter(
                        name=form.cleaned_data["name"]).exists():
                    cur_run = RunBase.objects.get(
                        name=form.cleaned_data["name"])

                if cur_run is None or cur_run.id == int(run_id):
                    if request.POST.get('save_button') is not None:
                        run_base.name = form.cleaned_data["name"]
                        run_base.description = form.cleaned_data["description"]
                        run_base.purpose = form.cleaned_data["purpose"]
                        # run_base.card_sequence = form.cleaned_data["card_sequence"]
                        run_base.directory_path = form.cleaned_data[
                            "directory_path"]
                        run_base.resolution = form.cleaned_data["resolution"]
                        # run_base.author = request.user
                        run_base.save()

                        path_dir = os.path.join(
                            str(run_base.resolution),
                            str(run_base.directory_path))
                        create_sub_dir(path_dir)

                        return HttpResponseRedirect(u'%s?status_message=%s' % (
                            reverse('run_setup'), (
                                u"Run {0} updated successfully".format(
                                    run_base.name))))
                    if request.POST.get('edit_run_details_button') is not None:
                        return HttpResponseRedirect(u'%s?info_message=%s' % (
                            reverse(
                                'card_sequence_update',
                                args=[run_id, run_base.card_sequence.id]), (
                                    u"Edit Card Sequence {0}".format(
                                        run_base.card_sequence))))
                else:
                    return HttpResponseRedirect(u'%s?status_message=%s' % (
                        reverse(
                            'run_update', args=[run_id]),
                        (u'Run with the name "{0}" already exists.'.format(
                            form.cleaned_data["name"]))))
    else:
        form = RunForm(instance=run_base)

    data = {'title': title, 'run_base': run_base, 'form': form}

    return data


@login_required
@render_to('gsi/run_new_card_sequence_list.html')
def run_new_card_sequence_list(request):
    title = 'Card Sequences'
    card_sequences = CardSequence.objects.all()
    cs_name = ''

    if request.method == "POST":
        if request.POST.get('cs_select'):
            for cs_id in request.POST.getlist('cs_select'):
                cur_cs = get_object_or_404(CardSequence, pk=cs_id)
                cs_name += '"' + cur_cs.name + '", '
                cur_cs.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('run_new_card_sequence_list'), (
                    u'Card Sequence: {0} ==> deleted.'.format(cs_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('run_new_card_sequence_list'),
                (u"To delete, select Card Sequence or more Card Sequences.")))

    data = {
        'title': title,
        'card_sequences': card_sequences,
    }

    return data


@login_required
@render_to('gsi/card_sequence.html')
def card_sequence(request, run_id):
    card_sequences = CardSequence.objects.all()
    title = 'Card Sequences'
    cs_name = ''

    if request.method == "POST":
        if request.POST.get('cs_select'):
            for cs_id in request.POST.getlist('cs_select'):
                cur_cs = get_object_or_404(CardSequence, pk=cs_id)
                cs_name += '"' + cur_cs.name + '", '
                cur_cs.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                'card_sequence', args=[run_id]), (
                    u'Card Sequence: {0} ==> deleted.'.format(cs_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse(
                    'card_sequence', args=[run_id]),
                (u"To delete, select Card Sequence or more Card Sequences.")))

    data = {
        'title': title,
        'card_sequences': card_sequences,
        'run_id': run_id,
    }

    return data


@login_required
@render_to('gsi/add_card_sequence.html')
def run_new_card_sequence_add(request):
    title = 'New Card Sequence'
    href = 'run_new_card_sequence_add'
    form = None

    if request.method == "POST":
        if request.POST.get('create_processing_card') is not None:
            return HttpResponseRedirect(reverse('proces_card_new_run'))
        elif request.POST.get('add_card_items_button') is not None:
            # import pdb;pdb.set_trace()
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'run_new_card_sequence_update', args=[card_sequence.id]
                ), (u"The new card item '{0}' was changed successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_and_continue_editing_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'run_new_card_sequence_update', args=[card_sequence.id]
                ), (u"The card sequence '{0}' created successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('new_run'),
                    (u"The card sequence '{0}' created successfully.".format(
                        card_sequence.name))))
        elif request.POST.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' %
                                        (reverse('run_new_card_sequence_list'),
                                         (u"Card Sequence created canceled")))
    else:
        form = CardSequenceCreateForm()

    data = {
        'title': title,
        'form': form,
        'href': href,
    }

    return data


@login_required
@render_to('gsi/card_sequence_update.html')
def run_new_card_sequence_update(request, cs_id):
    card_sequence = get_object_or_404(CardSequence, pk=cs_id)
    card_sequence_cards = CardSequence.cards.through.objects.filter(
        sequence_id=cs_id)
    title = 'Card Sequence %s' % (card_sequence.name)
    url_process_card = 'run_new_card_sequence_update'
    form = None

    if request.method == "POST":
        if request.POST.get('create_processing_card') is not None:
            return HttpResponseRedirect(
                reverse(
                    'proces_card_run_new_csid', args=[cs_id]))
        elif request.POST.get('add_card_items_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form, cs_id)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'run_new_card_sequence_update', args=[card_sequence.id]
                ), (u"The new card item '{0}' was changed successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_and_continue_editing_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form, cs_id)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'run_new_card_sequence_update', args=[card_sequence.id]
                ), (u"The new card item '{0}' was changed successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form, cs_id)

                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('new_run'), (
                        u"The card sequence '{0}' update successfully.".format(
                            card_sequence.name))))
        elif request.POST.get('delete_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                # card_sequence = create_update_card_sequence(form, cs_id)

                if request.POST.get('cs_select'):
                    cs_name = ''
                    for card_id in request.POST.getlist('cs_select'):
                        cur_cs = get_object_or_404(
                            CardSequence.cards.through, pk=card_id)
                        cs_name += '"' + str(cur_cs.card_item) + '", '
                        cur_cs.delete()

                    return HttpResponseRedirect(u'%s?status_message=%s' % (
                        reverse(
                            'run_new_card_sequence_update', args=[cs_id]),
                        (u'Card Sequence: {0} ==> deleted.'.format(cs_name))))
                else:
                    return HttpResponseRedirect(u'%s?warning_message=%s' % (
                        reverse(
                            'run_new_card_sequence_update', args=[cs_id]),
                        (u"To delete, select Card Sequence or more Card Sequences."
                         )))
        elif request.POST.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' %
                                        (reverse('run_new_card_sequence_list'),
                                         (u"Card Sequence update canceled")))
    else:
        form = CardSequenceCreateForm(instance=card_sequence)

    data = {
        'title': title,
        'form': form,
        'cs_id': cs_id,
        'card_sequence_cards': card_sequence_cards,
        'card_sequence': card_sequence,
        'url_process_card': url_process_card,
    }

    return data


@login_required
@render_to('gsi/add_card_sequence.html')
def add_card_sequence(request, run_id):
    card_items = CardItem.objects.all()
    title = 'New Card Sequence'
    href = 'add_card_sequence {0}'.format(run_id)
    form = None

    if request.method == "POST":
        if request.POST.get('create_processing_card') is not None:
            return HttpResponseRedirect(
                reverse(
                    'proces_card_runid', args=[run_id]))
        elif request.POST.get('add_card_items_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'card_sequence_update', args=[run_id, card_sequence.id]
                ), (u"The new card item '{0}' was changed successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_and_continue_editing_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'card_sequence_update', args=[run_id, card_sequence.id]
                ), (u"The card sequence '{0}' created successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif request.POST.get('save_button') is not None:
            form = CardSequenceCreateForm(request.POST)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form)

            return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                'card_sequence', args=[run_id]), (
                    u"The card sequence '{0}' created successfully.".format(
                        card_sequence.name))))
        elif request.POST.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' % (reverse(
                'card_sequence',
                args=[run_id]), (u"Card Sequence created canceled")))
    else:
        form = CardSequenceCreateForm()

    data = {
        'title': title,
        'form': form,
        'run_id': run_id,
        'card_items': card_items,
        'href': href,
    }

    return data


@login_required
@render_to('gsi/card_sequence_update.html')
def card_sequence_update(request, run_id, cs_id):
    home_var = HomeVariables.objects.all()
    rf_auxdata_path = home_var[0].RF_AUXDATA_DIR
    files, error = get_files(rf_auxdata_path, '.cfg')
    card_sequence = get_object_or_404(CardSequence, pk=cs_id)
    card_sequence_cards = CardSequence.cards.through.objects.filter(
        sequence_id=cs_id)
    title = 'Card Sequence {0}'.format(card_sequence.name)
    url_process_card = 'proces_card_sequence_card_edit'
    cs_configfile = card_sequence.configfile
    form = None

    REVERCE_URL = {
        'qrf': ['new_runid_csid_qrf', [run_id, cs_id]],
        'rfscore': ['new_runid_csid_rfscore', [run_id, cs_id]],
        'remap': ['new_runid_csid_remap', [run_id, cs_id]],
        'yearfilter': ['new_runid_csid_year_filter', [run_id, cs_id]],
        'collate': ['new_runid_csid_collate', [run_id, cs_id]],
        'preproc': ['new_runid_csid_preproc', [run_id, cs_id]],
        'mergecsv': ['new_runid_csid_mergecsv', [run_id, cs_id]],
        'rftrain': ['new_runid_csid_rftrain', [run_id, cs_id]],
        'randomforest': ['new_runid_csid_randomforest', [run_id, cs_id]],
        'calcstats': ['new_runid_csid_calcstats', [run_id, cs_id]],
        'cancel': ['card_sequence_update', [run_id, cs_id]]
    }

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            cs_id = data_post.getlist('run_id[]')

            for r in cs_id:
                # cur_run = get_object_or_404(RunBase, pk=int(r))
                cur_cs = get_object_or_404(
                    CardSequence.cards.through, pk=int(r))
                data += '"' + str(cur_cs) + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)

        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            cs_id = data_post['cur_run_id']
            cur_cs = get_object_or_404(
                CardSequence.cards.through, pk=int(cs_id))
            data = '<b>"' + str(cur_cs) + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        data_post = request.POST
        data_configfile = data_post.get('configfile', '')

        if data_post.get('new_card'):
            new_card = data_post.get('new_card')
            return HttpResponseRedirect(
                reverse(
                    REVERCE_URL[new_card][0], args=REVERCE_URL[new_card][1]))
        elif data_post.get('add_card_items_button') is not None:
            form = CardSequenceCreateForm(data_post, instance=card_sequence)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form, cs_id)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'card_sequence_update', args=[run_id, card_sequence.id]
                ), (u"The new card item '{0}' was changed successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif data_post.get('save_and_continue_editing_button') is not None:
            form = CardSequenceCreateForm(data_post, instance=card_sequence)

            if form.is_valid():
                if data_configfile:
                    card_sequence = create_update_card_sequence(
                        form, configfile=data_configfile, cs_id=cs_id)
                    update_qrf_rftrain_card(card_sequence, card_sequence_cards)
                else:
                    card_sequence = create_update_card_sequence(
                        form, cs_id=cs_id)

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'card_sequence_update', args=[run_id, card_sequence.id]
                ), (u"The new card item '{0}' was update successfully. You may edit it again below.".
                    format(card_sequence.name))))
        elif data_post.get('save_button') is not None:
            form = CardSequenceCreateForm(data_post, instance=card_sequence)

            if form.is_valid():
                if data_configfile:
                    card_sequence = create_update_card_sequence(
                        form, configfile=data_configfile, cs_id=cs_id)
                    update_qrf_rftrain_card(card_sequence, card_sequence_cards)
                else:
                    card_sequence = create_update_card_sequence(
                        form, cs_id=cs_id)

            return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                'run_update', args=[run_id]), (
                    u"The card sequence '{0}' update successfully.".format(
                        card_sequence.name))))
        elif data_post.get('delete_button') is not None:
            form = CardSequenceCreateForm(data_post, instance=card_sequence)

            if form.is_valid():
                card_sequence = create_update_card_sequence(form, cs_id)

                if data_post.get('cs_select'):
                    cs_name = ''
                    for cs_card_id in data_post.getlist('cs_select'):
                        # import pdb;pdb.set_trace()
                        cur_cs = get_object_or_404(
                            CardSequence.cards.through, pk=cs_card_id)
                        cs_name += '"' + str(cur_cs.card_item) + '", '
                        cur_cs.delete()

                    return HttpResponseRedirect(u'%s?status_message=%s' % (
                        reverse(
                            'card_sequence_update', args=[run_id, cs_id]),
                        (u'Card Items: {0} ==> deleted.'.format(cs_name))))
                else:
                    return HttpResponseRedirect(u'%s?warning_message=%s' % (
                        reverse(
                            'card_sequence_update', args=[run_id, cs_id]),
                        (u"To delete, select Card Item or more Card Items.")))
        elif data_post.get('del_current_btn'):
            card_id = data_post.get('del_current_btn')
            cur_cs = get_object_or_404(CardSequence.cards.through, pk=card_id)
            cs_name = '"' + str(cur_cs.card_item) + '", '
            cur_cs.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse(
                    'card_sequence_update', args=[run_id, cs_id]),
                (u'Card Item: {0} ==> deleted.'.format(cs_name))))
        elif data_post.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' % (reverse(
                'run_update', args=[run_id]), (
                    u'Card Sequence "{0}" created canceled'.format(
                        card_sequence.name))))
    else:
        form = CardSequenceCreateForm(instance=card_sequence)

    data = {
        'title': title,
        'form': form,
        'run_id': run_id,
        'cs_id': cs_id,
        'card_sequence_cards': card_sequence_cards,
        'card_sequence': card_sequence,
        'url_process_card': url_process_card,
        'files': files,
        'cs_configfile': cs_configfile
    }

    return data


# card item edit for card sequence
@login_required
@render_to('gsi/card_item_update.html')
def card_item_update(request, run_id, cs_id, card_item_id):
    card_sequence_card = get_object_or_404(
        CardSequence.cards.through, pk=card_item_id)
    title = 'Card ItemID {0}'.format(card_item_id)
    form = None

    if request.method == "POST":
        if request.POST.get('save_button') is not None:
            form = CardSequenceCardForm(
                request.POST, instance=card_sequence_card)

            if form.is_valid():
                for card in CardItem.objects.filter(
                        id=form.cleaned_data["card_item"].id):
                    card_sequence_card.card_item = card
                card_sequence_card.order = form.cleaned_data["order"]
                card_sequence_card.save()

                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'card_sequence_update', args=[run_id, cs_id]), (
                        u"Card Item {0} updated successfully".format(
                            card_sequence_card.card_item))))
        elif request.POST.get('cancel_button') is not None:
            return HttpResponseRedirect(u'%s?info_message=%s' % (reverse(
                'card_sequence_update', args=[run_id, cs_id]), (
                    u"Card Item {0} updated canceled".format(
                        card_sequence_card.card_item))))
    else:
        form = CardSequenceCardForm(instance=card_sequence_card)

    data = {
        'title': title,
        'card_sequence_card': card_sequence_card,
        'cs_id': cs_id,
        'form': form,
        'run_id': run_id,
    }

    return data


# submit a run
@login_required
@render_to('gsi/submit_run.html')
def submit_run(request):
    # import pdb;pdb.set_trace()
    run_bases = RunBase.objects.all().order_by('-date_modified')
    title = 'Submit a Run'
    name_runs = ''
    url_name = 'submit_run'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')
        if order_by in ('name', 'author', 'date_created', 'date_modified'):
            run_bases = run_bases.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                run_bases = run_bases.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        try:
            if 'cur_run_id' in data_post:
                run_id = data_post['cur_run_id']
                rb = get_object_or_404(RunBase, pk=run_id)
                execute_run = make_run(rb, request.user)

                if not execute_run:
                    data = u'Unable to execute the Run. Please contact the administrator!'
                    return HttpResponse(data)

                if execute_run['error']:
                    data = u'<b>ERROR</b>: {0}'.format(execute_run['error'])
                    return HttpResponse(data)

                num_cards = get_number_cards(execute_run['run'], request.user)
                now_date = datetime.now()
                now_date_formating = now_date.strftime("%d/%m/%Y")
                now_time = now_date.strftime("%H:%M")
                data = u'Run "{0}" has been submitted to back end and {1} on {2}<br>Processed {3} Cards'.\
                 format(rb.name, now_time, now_date_formating, num_cards)

                return HttpResponse(data)
            else:
                data = u"For start choose Run"
                return HttpResponse(data)

            # if request.POST.get('execute_runs', ''):
            # 	run_id = request.POST.get('execute_runs', '')
            # 	# for run_id in id_runs:
            # 	# 	rb = get_object_or_404(RunBase, pk=run_id)
            # 	# 	# execute_run = make_run(rb, request.user)
            # 	# 	name_runs += '"' + str(rb.name) + '", '
            #
            # 	rb = get_object_or_404(RunBase, pk=run_id)
            # 	execute_run = make_run(rb, request.user)
            #
            # 	if not execute_run:
            # 		return HttpResponseRedirect(u'%s?danger_message=%s' %
            # 									(reverse('submit_run'),
            # 									 (u'Unable to execute the Run. \
            # 									 Please contact the administrator!')))
            #
            # 	now_date = datetime.now()
            # 	now_date_formating = now_date.strftime("%d/%m/%Y")
            # 	now_time = now_date.strftime("%H:%M")
            #
            # 	print 'execute_run'
            #
            # 	return HttpResponseRedirect(u'%s?status_message=%s' %
            # 				(reverse('submit_run'),
            # 				 (u'Run "{0}" has been submitted to back end and {1} on {2}'.
            # 				  format(rb.name, now_time, now_date_formating)))
            # 	)
            # else:
            # 	return HttpResponseRedirect(u'%s?warning_message=%s' % (reverse('submit_run'),
            # 								 (u"For start choose Run(s)"))
            # 	)
        except Exception, e:
            print 'ERROR submit_run ====================== ', e
            # ***********************************************************************
            # write log file
            path_file = '/home/gsi/LOGS/submit_run.log'
            now = datetime.now()
            log_submit_run_file = open(path_file, 'a')
            log_submit_run_file.writelines('{0}\n'.format(now))
            log_submit_run_file.writelines('ERROR = {0}:\n'.format(e))
            log_submit_run_file.writelines('\n\n\n')
            log_submit_run_file.close()
            # ***********************************************************************

        # paginations
    model_name = paginations(request, run_bases)

    data = {
        'title': title,
        'run_bases': model_name,
        'model_name': model_name,
        'url_name': url_name,
    }

    return data


# execute run
@login_required
@render_to('gsi/execute_run.html')
def execute_runs(request, run_id):
    title = 'Execute Run'
    list_run_id = run_id.split('_')
    name_runs = ''
    messages = []

    for run in list_run_id:
        name_runs += '"' + str(
            get_object_or_404(
                Run, pk=int(run)).run_base.name) + '", '
        messages.append(
            'It has been assigned unique run ID: {0}.\nTo view progress of this run use \
						the view progress option on the main menu.\n'.format(run))

    data = {
        'title': title,
        'run_id': run_id,
        'messages': messages,
    }

    return data


# run progress
@login_required
@render_to('gsi/run_progress.html')
def run_progress(request):
    runs = Run.objects.all().order_by('-id')
    title = 'Run Progress'
    url_name = 'run_progress'
    run_name = ''

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')
        if order_by in ('run_base', ):
            runs = runs.order_by('run_base__name')

            if request.GET.get('reverse', '') == '1':
                runs = runs.reverse()

        if order_by in ('id', 'run_date', 'state', 'user'):
            runs = runs.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                runs = runs.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Run, pk=int(r))
                data += '"' + str(cur_run) + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        if request.POST.get('run_progress'):
            for run_id in request.POST.getlist('run_progress'):
                cur_run = get_object_or_404(Run, pk=run_id)
                run_name += '"' + str(cur_run) + '", '
                cur_run.delete()

                # delete folder Run(s) from server
                try:
                    run_folder = 'R_{0}'.format(run_id)
                    path = os.path.join(PATH_RUNS_SCRIPTS, run_folder)
                    shutil.rmtree(path)
                except OSError:
                    pass

            run_name = run_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('run_progress'),
                (u'Run(s): {0} ==> deleted.'.format(run_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('run_progress'),
                (u"To delete, select Run or more Runs.")))

    # paginations
    model_name = paginations(request, runs)

    data = {
        'title': title,
        'runs': model_name,
        'url_name': url_name,
        'model_name': model_name,
    }

    return data


# details run
@login_required
@render_to('gsi/run_details.html')
def run_details(request, run_id):
    sub_title = 'The View Log file select and hit view'
    runs_step = RunStep.objects.filter(parent_run=run_id)
    runs_step.order_by('card_item__order')
    url_name = 'run_details'

    if runs_step:
        title = 'Run "{0}" Details'.format(runs_step[0].parent_run)
    else:
        title = 'No data to display'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')
        if order_by in ('card_item_id', ):
            runs_step = runs_step.order_by('card_item__id')

            if request.GET.get('reverse', '') == '1':
                runs_step = runs_step.reverse()

        if order_by in ('card_item', ):
            runs_step = runs_step.order_by('card_item__card_item__name')

            if request.GET.get('reverse', '') == '1':
                runs_step = runs_step.reverse()

        if order_by in ('order', ):
            runs_step = runs_step.order_by('card_item__order')

            if request.GET.get('reverse', '') == '1':
                runs_step = runs_step.reverse()

        if order_by in ('start_date', 'state'):
            runs_step = runs_step.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                runs_step = runs_step.reverse()

    if request.method == "POST":
        if request.POST.get('details_file'):
            step = get_object_or_404(
                RunStep, pk=request.POST.get('details_file'))

            if request.POST.get('out_button', ''):
                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse(
                        'view_log_file',
                        args=[run_id, step.card_item.id, 'Out']),
                    (u'Log Out file for the Card "{0}".'.format(step.card_item)
                     )))
            elif request.POST.get('err_button', ''):
                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'view_log_file',
                    args=[run_id, step.card_item.id, 'Error']), (
                        u'Log Error file for the Card "{0}".'.format(
                            step.card_item))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (reverse(
                'run_details',
                args=[run_id]), (u"To view the Card Log, select Card.")))

    # paginations
    model_name = paginations(request, runs_step)

    data = {
        'title': title,
        'sub_title': sub_title,
        'run_id': run_id,
        'runs_step': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'obj_id': run_id,
    }

    return data


# view out/error log files for cards
@login_required
@render_to('gsi/view_log_file.html')
def view_log_file(request, run_id, card_id, status):
    log_info = ''
    run = get_object_or_404(Run, pk=run_id)
    runs_step = RunStep.objects.filter(parent_run=run_id).first()
    run_step_card = RunStep.objects.filter(card_item__id=card_id).first()

    title = 'Log {0} file for the Card Item "{1}"'.format(status, run)
    sub_title = 'The View Log file select and hit view'

    try:
        log = get_object_or_404(Log, pk=run.log.id)
        log_path = log.log_file_path
    except Exception:
        log_name = '{}_{}.log'.format(run.id, run_step_card.card_item.id)
        log_path = get_path_folder_run(run)
        log = Log.objects.create(
            name=log_name, log_file=log_name, log_file_path=log_path)
        run.log = log
        run.save()

    if status == 'Out':
        try:
            card_name = 'runcard_{0}.out'.format(card_id)
            path_log_file = os.path.join(str(log_path), str(card_name))
            fd = open(path_log_file, 'r')
            for line in fd.readlines():
                log_info += line + '<br />'
        except Exception, e:
            print 'ERROR Out view_log_file: ', e
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse(
                    'run_details', args=[run_id]),
                (u'Log Out file "{0}" not found.'.format(card_name))))
    elif status == 'Error':
        try:
            card_name = 'runcard_{0}.err'.format(card_id)
            path_log_file = os.path.join(str(log_path), str(card_name))
            fd = open(path_log_file, 'r')
            for line in fd.readlines():
                log_info += line + '<br />'
        except Exception, e:
            print 'ERROR Error view_log_file: ', e
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse(
                    'run_details', args=[run_id]),
                (u'Log Error file "{0}" not found.'.format(card_name))))

    data = {
        'title': title,
        'run_id': run_id,
        'card_id': card_id,
        'log_info': log_info,
    }

    return data


# view out/error log files for cards
@login_required
@render_to('gsi/view_log_file_sub_card.html')
def view_log_file_sub_card(request, run_id, card_id, count, status):
    log_info = ''

    runs_step = RunStep.objects.filter(parent_run=run_id).first()
    run_step_card = RunStep.objects.filter(card_item__id=card_id).first()

    title = 'Log {0} file for the Sub Card "{1}"'.format(
        status, run_step_card.card_item)
    sub_title = 'The View Log file select and hit view'

    run = get_object_or_404(Run, pk=run_id)

    try:
        log = get_object_or_404(Log, pk=run.log.id)
        log_path = log.log_file_path
    except Exception:
        log_name = '{}_{}.log'.format(run.id, run_step_card.card_item.id)
        log_path = get_path_folder_run(run)
        log = Log.objects.create(
            name=log_name, log_file=log_name, log_file_path=log_path)
        run.log = log
        run.save()

    # card_name = ''
    # path_log_file = os.path.join(str(log_path), str(card_name))

    if status == 'Out':
        card_name = 'runcard_{0}_{1}.out'.format(card_id, count)
        path_log_file = os.path.join(str(log_path), str(card_name))
        try:
            fd = open(path_log_file, 'r')
            for line in fd.readlines():
                log_info += line + '<br />'
        except Exception, e:
            print 'ERROR Out view_log_file_sub_card: ', e
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse(
                    'sub_card_details', args=[run_id, card_id]),
                (u'Log Out file "{0}" not found.'.format(card_name))))
    elif status == 'Error':
        card_name = 'runcard_{0}_{1}.err'.format(card_id, count)
        path_log_file = os.path.join(str(log_path), str(card_name))
        try:
            fd = open(path_log_file, 'r')
            for line in fd.readlines():
                log_info += line + '<br />'
        except Exception, e:
            print 'ERROR Error view_log_file_sub_card: ', e
            return HttpResponseRedirect(u'%s?danger_message=%s' % (
                reverse(
                    'sub_card_details', args=[run_id, card_id]),
                (u'Log Error file "{0}" not found.'.format(card_name))))

    data = {
        'title': title,
        'run_id': run_id,
        'card_id': card_id,
        'log_info': log_info,
    }

    return data


# details parallel card of run
@login_required
@render_to('gsi/sub_card_details.html')
def sub_card_details(request, run_id, card_id):
    url_name = 'sub_card_details'
    sub_cards = SubCardItem.objects.filter(run_id=run_id, card_id=card_id)
    sub_cards.order_by('sub_cards.start_time')
    # runs_step = RunStep.objects.filter(parent_run=run_id).first()
    run_step_card = RunStep.objects.filter(card_item__id=card_id).first()
    title = 'Sub Cards of Card "{0}" Details'.format(run_step_card.card_item)
    sub_title = 'The View Log file select and hit view'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', 'start_date', 'start_time', 'state'):
            sub_cards = sub_cards.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                sub_cards = sub_cards.reverse()

    if request.method == "POST":
        if request.POST.get('details_file'):

            if request.POST.get('err_button', ''):
                log_err = request.POST.get('details_file')
                count = log_err.split('_')[1]
                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'view_log_file_sub_card',
                    args=[run_id, card_id, count, 'Error']), (
                        u'Log Error file for the Card "{0}".'.format(
                            run_step_card.card_item))))
            elif request.POST.get('out_button', ''):
                log_err = request.POST.get('details_file')
                count = log_err.split('_')[1]
                return HttpResponseRedirect(u'%s?status_message=%s' % (reverse(
                    'view_log_file_sub_card',
                    args=[run_id, card_id, count, 'Out']), (
                        u'Log Out file for the Card "{0}".'.format(
                            run_step_card.card_item))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse(
                    'sub_card_details', args=[run_id, card_id]),
                (u"To view the Card Log, select Card.")))

    # paginations
    model_name = paginations(request, sub_cards)

    data = {
        'title': title,
        'sub_title': sub_title,
        'run_id': run_id,
        'card_id': card_id,
        'sub_cards': model_name,
        'card_name': run_step_card.card_item,
        'model_name': model_name,
        'url_name': url_name,
        'obj_id': run_id,
    }

    return data


# setup static data
@login_required
@render_to('gsi/static_data_setup.html')
def static_data_setup(request):
    title = 'Setup Static Data'
    data = {'title': title, }

    return data


# setup home variable
@login_required
@render_to('gsi/home_variable_setup.html')
def home_variable_setup(request):
    title = 'Home Variables'
    form = None
    url_name = 'home_variable'
    but_name = 'static_data'

    try:
        variables = HomeVariables.objects.get(pk=1)
    except HomeVariables.DoesNotExist:
        variables = ''

    if request.method == "POST":
        form = HomeVariablesForm(request.POST)

        if form.is_valid():
            if variables:
                variables.SAT_TIF_DIR_ROOT = form.cleaned_data["SAT_TIF_DIR_ROOT"]
                variables.RF_DIR_ROOT = form.cleaned_data["RF_DIR_ROOT"]
                variables.USER_DATA_DIR_ROOT = form.cleaned_data["USER_DATA_DIR_ROOT"]
                variables.MODIS_DIR_ROOT = form.cleaned_data["MODIS_DIR_ROOT"]
                variables.RF_AUXDATA_DIR = form.cleaned_data["RF_AUXDATA_DIR"]
                variables.SAT_DIF_DIR_ROOT = form.cleaned_data["SAT_DIF_DIR_ROOT"]
                variables.save()
            else:
                variables = HomeVariables.objects.create(
                        SAT_TIF_DIR_ROOT = form.cleaned_data["SAT_TIF_DIR_ROOT"],
                        RF_DIR_ROOT = form.cleaned_data["RF_DIR_ROOT"],
                        USER_DATA_DIR_ROOT = form.cleaned_data["USER_DATA_DIR_ROOT"],
                        MODIS_DIR_ROOT = form.cleaned_data["MODIS_DIR_ROOT"],
                        RF_AUXDATA_DIR = form.cleaned_data["RF_AUXDATA_DIR"],
                        SAT_DIF_DIR_ROOT = form.cleaned_data["SAT_DIF_DIR_ROOT"]
                    )

            if request.POST.get('save_button') is not None:
                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('home_variable_setup'),
                    (u"Home variables successfully updated")))
            if request.POST.get('save_and_continue_button') is not None:
                return HttpResponseRedirect(u'%s?status_message=%s' % (
                    reverse('home_variable_setup'),
                    (u"Home variables successfully updated")))
    else:
        if variables:
            form = HomeVariablesForm(instance=variables)
        else:
            form = HomeVariablesForm()

    data = {
        'title': title,
        'variables': variables,
        'form': form,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# environment group
@login_required
@render_to('gsi/environment_groups_list.html')
def environment_groups(request):
    title = 'Environment Groups'
    environments = VariablesGroup.objects.all()
    env_name = ''
    url_name = 'environment_groups'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', ):
            environments = environments.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                environments = environments.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(VariablesGroup, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(VariablesGroup, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('env_select'):
            for env_id in request.POST.getlist('env_select'):
                cur_env = get_object_or_404(VariablesGroup, pk=env_id)
                env_name += '"' + str(cur_env.name) + '", '
                cur_env.delete()

            envs_ids = '_'.join(request.POST.getlist('env_select'))
            env_name = env_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('environment_groups'), (
                    u'Environment Groups: {0} ==> deleted.'.format(env_name))))
        elif request.POST.get('delete_button'):
            cur_env = get_object_or_404(
                VariablesGroup, pk=request.POST.get('delete_button'))
            env_name += '"' + str(cur_env.name) + '", '
            cur_env.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('environment_groups'), (
                    u'Environment Group: {0} ==> deleted.'.format(env_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('environment_groups'),
                (u"To delete, select Group or more Groups.")))

    # paginations
    model_name = paginations(request, environments)

    data = {
        'title': title,
        'environments': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# environment group add
@login_required
@render_to('gsi/static_data_item_edit.html')
def environment_group_add(request):
    title = 'Environment Group Add'
    url_form = 'environment_group_add'
    template_name = 'gsi/_env_group_form.html'
    reverse_url = {
        'save_button': 'environment_groups',
        'save_and_another': 'environment_group_add',
        'save_and_continue': 'environment_group_edit',
        'cancel_button': 'environment_groups'
    }
    func = var_group_update_create
    form = None
    url_name = 'environment_groups'
    but_name = 'static_data'

    if request.method == "POST":
        response = get_post(request, EnvironmentGroupsForm,
                            'Environment Group', reverse_url, func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = EnvironmentGroupsForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# environment group add
@login_required
@render_to('gsi/static_data_item_edit.html')
def environment_group_edit(request, env_id):
    env_item = get_object_or_404(VariablesGroup, pk=env_id)
    title = 'Environment Group "{0}" Edit'.format(env_item.name)
    url_form = 'environment_group_edit'
    template_name = 'gsi/_env_group_form.html'
    reverse_url = {
        'save_button': 'environment_groups',
        'save_and_another': 'environment_group_add',
        'save_and_continue': 'environment_groups',
        'cancel_button': 'environment_groups'
    }
    func = var_group_update_create
    form = None
    url_name = 'environment_groups'
    but_name = 'static_data'

    if request.method == "POST":
        # import pdb;pdb.set_trace()
        response = get_post(
            request,
            EnvironmentGroupsForm,
            'Environment Group',
            reverse_url,
            func,
            item_id=env_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = EnvironmentGroupsForm(instance=env_item)

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'item_id': env_id,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# area
@login_required
@render_to('gsi/areas_list.html')
def areas(request):
    title = 'Areas'
    areas = Area.objects.all()
    area_name = ''
    url_name = 'areas'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', ):
            areas = areas.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                areas = areas.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Area, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(Area, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('area_select'):
            for area_id in request.POST.getlist('area_select'):
                cur_area = get_object_or_404(Area, pk=area_id)
                area_name += '"' + cur_area.name + '", '
                cur_area.delete()

            area_ids = '_'.join(request.POST.getlist('env_select'))

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('areas'),
                (u'Areas: {0} ==> deleted.'.format(area_name))))
        elif request.POST.get('delete_button'):
            cur_area = get_object_or_404(
                Area, pk=request.POST.get('delete_button'))
            area_name += '"' + cur_area.name + '", '
            cur_area.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('areas'),
                (u'Areas: {0} ==> deleted.'.format(area_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('areas'), (u"To delete, select Area or more Areas.")))

    # paginations
    model_name = paginations(request, areas)

    data = {
        'title': title,
        'areas': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# area add
@login_required
@render_to('gsi/static_data_item_edit.html')
def area_add(request):
    title = 'Area Add'
    url_form = 'area_add'
    template_name = 'gsi/_area_form.html'
    reverse_url = {
        'save_button': 'areas',
        'save_and_another': 'area_add',
        'save_and_continue': 'area_edit',
        'cancel_button': 'areas'
    }
    func = area_update_create
    form = None
    url_name = 'areas'
    but_name = 'static_data'
    available_tiles = Tile.objects.all()

    if request.method == "POST":
        response = get_post(request, AreasForm, 'Area', reverse_url, func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = AreasForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_tiles': available_tiles,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# area edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def area_edit(request, area_id):
    area = get_object_or_404(Area, pk=area_id)
    title = 'Area Edit "%s"' % (area.name)
    url_form = 'area_edit'
    template_name = 'gsi/_area_form.html'
    reverse_url = {
        'save_button': 'areas',
        'save_and_another': 'area_add',
        'save_and_continue': 'area_edit',
        'cancel_button': 'areas'
    }
    func = area_update_create
    form = None
    url_name = 'areas'
    but_name = 'static_data'
    chosen_tiles = area.tiles.all()
    available_tiles = Tile.objects.exclude(id__in=area.tiles.values_list(
        'id', flat=True))

    if request.method == "POST":
        response = get_post(
            request, AreasForm, 'Area', reverse_url, func, item_id=area_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = AreasForm(instance=area)

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'item_id': area_id,
        'available_tiles': available_tiles,
        'chosen_tiles': chosen_tiles,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# year group group
@login_required
@render_to('gsi/years_group_list.html')
def years_group(request):
    title = 'Years Groups'
    years_groups = YearGroup.objects.all()
    yg_name = ''
    url_name = 'years_group'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', ):
            years_groups = years_groups.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                years_groups = years_groups.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(YearGroup, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(YearGroup, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('yg_select'):
            for yg_id in request.POST.getlist('yg_select'):
                cur_yg = get_object_or_404(YearGroup, pk=yg_id)
                yg_name += '"' + cur_yg.name + '", '
                cur_yg.delete()
            yg_name = yg_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('years_group'),
                (u'Years Groups: {0} ==> deleted.'.format(yg_name))))
        elif request.POST.get('delete_button'):
            cur_yg = get_object_or_404(
                YearGroup, pk=request.POST.get('delete_button'))
            yg_name += '"' + cur_yg.name + '"'
            cur_yg.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('years_group'),
                (u'Years Group: {0} ==> deleted.'.format(yg_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('years_group'),
                (u"To delete, select Years Group or more Years Groups.")))

    # paginations
    model_name = paginations(request, years_groups)

    data = {
        'title': title,
        'years_groups': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# year group add
@login_required
@render_to('gsi/static_data_item_edit.html')
def years_group_add(request):
    title = 'Years Groups Add'
    url_form = 'years_group_add'
    url_name = 'years_group'
    but_name = 'static_data'
    template_name = 'gsi/_years_group_form.html'
    reverse_url = {
        'save_button': 'years_group',
        'save_and_another': 'years_group_add',
        'save_and_continue': 'years_group_edit',
        'cancel_button': 'years_group'
    }
    func = yg_update_create
    form = None
    available_years = Year.objects.all()

    if request.method == "POST":
        response = get_post(request, YearGroupForm, 'Year Group', reverse_url,
                            func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = AreasForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_years': available_years,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# year group edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def years_group_edit(request, yg_id):
    years_group = get_object_or_404(YearGroup, pk=yg_id)
    title = 'YearGroup Edit "%s"' % (years_group.name)
    url_name = 'years_group'
    but_name = 'static_data'
    url_form = 'years_group_edit'
    template_name = 'gsi/_years_group_form.html'
    reverse_url = {
        'save_button': 'years_group',
        'save_and_another': 'years_group_add',
        'save_and_continue': 'years_group_edit',
        'cancel_button': 'years_group'
    }
    func = yg_update_create
    form = None
    chosen_years = years_group.years.all()
    available_years = Year.objects.exclude(
        id__in=years_group.years.values_list(
            'id', flat=True))

    if request.method == "POST":
        response = get_post(
            request,
            YearGroupForm,
            'Year Group',
            reverse_url,
            func,
            item_id=yg_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = AreasForm(instance=years_group)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': yg_id,
        'available_years': available_years,
        'chosen_years': chosen_years,
    }

    return data


# satellite list
@login_required
@render_to('gsi/satellite_list.html')
def satellite(request):
    title = 'Satellites'
    satellites = Satellite.objects.all()
    satellite_name = ''
    url_name = 'satellite'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', ):
            satellites = satellites.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                satellites = satellites.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Satellite, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(Satellite, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('satellite_select'):
            for satellite_id in request.POST.getlist('satellite_select'):
                cur_satellite = get_object_or_404(Satellite, pk=satellite_id)
                satellite_name += '"' + cur_satellite.name + '", '
                cur_satellite.delete()

            satellite_name = satellite_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('satellite'),
                (u'Satellites: {0} ==> deleted.'.format(satellite_name))))
        elif request.POST.get('delete_button'):
            cur_satellite = get_object_or_404(
                Satellite, pk=request.POST.get('delete_button'))
            satellite_name += '"' + cur_satellite.name + '"'
            cur_satellite.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('satellite'),
                (u'Satellite: {0} ==> deleted.'.format(satellite_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('satellite'),
                (u"To delete, select Satellite or more Satellites.")))

    # paginations
    model_name = paginations(request, satellites)

    data = {
        'title': title,
        'satellites': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# satellite add
@login_required
@render_to('gsi/static_data_item_edit.html')
def satellite_add(request):
    title = 'Satellites Add'
    url_form = 'satellite_add'
    url_name = 'satellite'
    but_name = 'static_data'
    template_name = 'gsi/_satellite_form.html'
    reverse_url = {
        'save_button': 'satellite',
        'save_and_another': 'satellite_add',
        'save_and_continue': 'satellite_edit',
        'cancel_button': 'satellite'
    }
    func = satellite_update_create
    form = None
    available_satellite = Satellite.objects.all()

    if request.method == "POST":
        response = get_post(request, SatelliteForm, 'Satellite', reverse_url,
                            func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = SatelliteForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_satellite': available_satellite,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# satellite edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def satellite_edit(request, satellite_id):
    satellite = get_object_or_404(Satellite, pk=satellite_id)
    title = 'Satellite Edit "%s"' % (satellite.name)
    url_name = 'satellite'
    but_name = 'static_data'
    url_form = 'satellite_edit'
    template_name = 'gsi/_satellite_form.html'
    reverse_url = {
        'save_button': 'satellite',
        'save_and_another': 'satellite_add',
        'save_and_continue': 'satellite_edit',
        'cancel_button': 'satellite'
    }
    func = satellite_update_create
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            SatelliteForm,
            'Satellite',
            reverse_url,
            func,
            item_id=satellite_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = SatelliteForm(instance=satellite)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': satellite_id,
    }

    return data


# InputDataDirectory list
@login_required
@render_to('gsi/input_data_dir_list.html')
def input_data_dir_list(request):
    title = 'Input Data Directory'
    input_data_dirs = InputDataDirectory.objects.all()
    home_var = HomeVariables.objects.all()
    input_data_dir_name = ''
    url_name = 'input_data_dir_list'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', ):
            input_data_dirs = input_data_dirs.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                input_data_dirs = input_data_dirs.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(InputDataDirectory, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(InputDataDirectory, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('input_data_dirs_select'):
            for dir_id in request.POST.getlist('input_data_dirs_select'):
                cur_dir = get_object_or_404(InputDataDirectory, pk=dir_id)
                input_data_dir_name += '"' + cur_dir.name + '", '
                cur_dir.delete()

                dir_path = os.path.join(home_var[0].RF_AUXDATA_DIR,
                                        cur_dir.name)
                if os.path.exists(dir_path):
                    shutil.rmtree(dir_path)

            input_data_dir_name = input_data_dir_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('input_data_dir_list'), (
                    u'Input Data Directorys "{0}": deleted.'.format(
                        input_data_dir_name))))
        elif request.POST.get('delete_button'):
            cur_dir = get_object_or_404(
                InputDataDirectory, pk=request.POST.get('delete_button'))
            input_data_dir_name += '"' + cur_dir.name + '"'
            cur_dir.delete()
            dir_path = os.path.join(home_var[0].RF_AUXDATA_DIR, cur_dir.name)
            if os.path.exists(dir_path):
                shutil.rmtree(dir_path)

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('input_data_dir_list'), (
                    u'Input Data Directory "{0}": deleted.'.format(
                        input_data_dir_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('input_data_dir_list'),
                (u"To delete, select Directory or more Directorys.")))

    # paginations
    model_name = paginations(request, input_data_dirs)

    data = {
        'title': title,
        'input_data_dirs': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# InputDataDirectory add
@login_required
@render_to('gsi/static_data_item_edit.html')
def input_data_dir_add(request):
    title = 'Input Data Directory Add'
    url_form = 'input_data_dir_add'
    url_name = 'input_data_dir_list'
    but_name = 'static_data'
    template_name = 'gsi/_input_data_dir_form.html'
    reverse_url = {
        'save_button': 'input_data_dir_list',
        'save_and_another': 'input_data_dir_add',
        'save_and_continue': 'input_data_dir_edit',
        'cancel_button': 'input_data_dir_list'
    }
    func = data_dir_update_create
    form = None
    available_files = InputDataDirectory.objects.all()

    if request.method == "POST":
        response = get_post(request, InputDataDirectoryForm,
                            'Input Data Directory', reverse_url, func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = InputDataDirectoryForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_files': available_files,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# InputDataDirectory edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def input_data_dir_edit(request, dir_id):
    data_dir = get_object_or_404(InputDataDirectory, pk=dir_id)
    title = 'Input Data Directory Edit "%s"' % (data_dir.name)
    url_name = 'input_data_dir_list'
    but_name = 'static_data'
    url_form = 'input_data_dir_edit'
    template_name = 'gsi/_input_data_dir_form.html'
    reverse_url = {
        'save_button': 'input_data_dir_list',
        'save_and_another': 'input_data_dir_add',
        'save_and_continue': 'input_data_dir_edit',
        'cancel_button': 'input_data_dir_list'
    }
    func = data_dir_update_create
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            InputDataDirectoryForm,
            'Input Data Directory',
            reverse_url,
            func,
            item_id=dir_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = InputDataDirectoryForm(instance=data_dir)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': dir_id,
    }

    return data


# Cards List
@login_required
@render_to('gsi/cards_list.html')
def cards_list(request, *args, **kwargs):
    title = 'Editing Cards'
    cards_all = CardItem.objects.all()
    card_list = []
    cards_name = ''
    url_name = 'cards_list'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', 'content_type__model'):
            cards_all = cards_all.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                cards_all = cards_all.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            card_id = data_post.getlist('run_id[]')

            for c in card_id:
                cur_card = get_object_or_404(CardItem, pk=int(c))
                data += '"' + str(cur_card) + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            card_id = data_post['cur_run_id']
            cur_card = get_object_or_404(CardItem, pk=int(card_id))
            data = '<b>"' + str(cur_card) + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        if request.POST.get('card_select'):
            for card_id in request.POST.getlist('card_select'):
                cur_card = get_object_or_404(CardItem, pk=card_id)
                cards_name += '"' + str(cur_card) + '", '
                content_type_card = ContentType.objects.get(
                    id=cur_card.content_type_id)
                class_obj = content_type_card.get_object_for_this_type(
                    name=str(cur_card))
                # print 'str(cur_card) =========================== ', str(cur_card)
                cur_card.delete()
                class_obj.delete()

            cards_name = cards_name[:-2]

            # print 'cards_name ===================== ', cards_name

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('cards_list'),
                (u'Cards: {0} ==> deleted.'.format(cards_name))))
        elif request.POST.get('delete_button'):
            cur_card = get_object_or_404(
                CardItem, pk=request.POST.get('delete_button'))
            cards_name += '"' + str(cur_card) + '"'
            content_type_card = ContentType.objects.get(
                id=cur_card.content_type_id)
            class_obj = content_type_card.get_object_for_this_type(
                name=str(cur_card))
            cur_card.delete()
            class_obj.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('cards_list'),
                (u'Card: {0} ==> deleted.'.format(cards_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('cards_list'),
                (u"To delete, select Card or more Cards.")))

    # paginations
    model_name = paginations(request, cards_all)

    data = {
        'title': title,
        'cards': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Cards List
@login_required
@render_to('gsi/card_editions.html')
def card_edit(request, card_id):
    data_card = get_object_or_404(CardItem, pk=card_id)
    title = 'Card Editing "%s"' % (data_card)
    url_name = 'cards_list'
    but_name = 'static_data'
    url_form = 'card_edit'
    card_model = data_card.content_type.model if data_card.content_type.model != 'yearfilter' else 'year_filter'
    template_name = 'cards/_{0}_form.html'.format(card_model)
    func_dict = {
        'qrf': qrf_update_create,
        'rfscore': rfscore_update_create,
        'remap': remap_update_create,
        'yearfilter': year_filter_update_create,
        'collate': collate_update_create,
        'preproc': preproc_update_create,
        'mergecsv': mergecsv_update_create,
        'rftrain': rftrain_update_create,
        'randomforest': randomforest_update_create,
    }

    form_dict = {
        'qrf': QRFForm,
        'rfscore': RFScoreForm,
        'remap': RemapForm,
        'yearfilter': YearFilterForm,
        'collate': CollateForm,
        'preproc': PreProcForm,
        'mergecsv': MergeCSVForm,
        'rftrain': RFTrainForm,
        'randomforest': RandomForestForm,
    }

    # print 'template_name ========================= ', template_name
    # print 'card_model ========================= ', card_model
    # print 'data_card ========================= ', data_card

    content_type_name = ContentType.objects.get(
        app_label="cards", model=data_card.content_type.model)
    class_model = content_type_name.model_class()
    card_name = content_type_name.get_object_for_this_type(name=data_card)
    cur_card = get_object_or_404(class_model, pk=card_name.id)

    # print 'card_name ========================== ', card_name
    # print 'class_model ========================== ', class_model
    # print 'content_type_name ========================== ', content_type_name
    # print 'card_name ID ========================== ', card_name.id

    # template_name = 'gsi/_input_data_dir_form.html'
    reverse_url = {
        'save_button': 'cards_list',
        'save_and_another': 'input_data_dir_add',
        'save_and_continue': 'cards_edit',
        'cancel_button': 'cards_list'
    }
    func = func_dict[data_card.content_type.model]
    card_form = form_dict[data_card.content_type.model]
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            card_form,
            str(content_type_name),
            reverse_url,
            func,
            item_id=card_name.id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = card_form(instance=card_name)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'card_id': card_id,
    }

    return data


# audit history
@login_required
@render_to('gsi/audit_history.html')
def audit_history(request, run_id):
    # Audit record for  MATT_COLLATE_TESTR_29th_Feb
    # get_logs(element, element_id, limit=None, user=None)
    run_base = get_object_or_404(RunBase, pk=run_id)
    title = 'Audit record for "{0}"'.format(run_base.name)
    logs = []

    logs.extend(list(get_logs('RunBase', run_base.id)))
    logs.extend(list(get_logs('Run', run_base.id)))

    data = {
        'title': title,
        'run_id': run_id,
        'logs': logs,
    }

    return data


# view results
@login_required
@render_to('gsi/view_results.html')
def view_results(request, run_id):
    run_base = get_object_or_404(RunBase, pk=run_id)
    title = 'View results "{0}"'.format(run_base.name)
    dir_root = get_dir_root_static_path()
    resolution = run_base.resolution
    folder = run_base.directory_path
    static_dir_root_path = str(dir_root['static_dir_root_path']) + '/' + str(
        resolution) + '/' + str(folder)
    static_dir_root_path = slash_remove_from_path(static_dir_root_path)
    static_dir_root = str(dir_root['static_dir_root']) + '/' + str(
        resolution) + '/' + str(folder)
    static_dir_root = slash_remove_from_path(static_dir_root)

    dirs, files, info_message = get_files_dirs(static_dir_root,
                                               static_dir_root_path)

    if info_message:
        info_message = u'For run "{0}" there are no results to show.'.format(
            run_base.name)

    data = {
        'run_id': run_id,
        'title': title,
        'info_message': info_message,
        'dirs': dirs,
        'files': files,
        'prev_dir': 'd',
    }

    return data


# view results
@login_required
@render_to('gsi/view_results_folder.html')
def view_results_folder(request, run_id, prev_dir, dir):
    run_base = get_object_or_404(RunBase, pk=run_id)
    title = 'View results "{0}"'.format(run_base.name)
    back_prev = ''
    back_cur = ''

    dir_root = get_dir_root_static_path()
    resolution = run_base.resolution
    folder = run_base.directory_path

    static_dir_root_path = str(dir_root['static_dir_root_path']) + '/' + str(
        resolution) + '/' + str(folder)
    static_dir_root_path = slash_remove_from_path(static_dir_root_path)
    static_dir_root = str(dir_root['static_dir_root']) + '/' + str(
        resolution) + '/' + str(folder)
    static_dir_root = slash_remove_from_path(static_dir_root)
    static_dir_root_path_folder = static_dir_root_path
    static_dir_root_folder = static_dir_root

    if prev_dir != 'd':
        list_dir = prev_dir.split('%')
        back_prev = '%'.join(list_dir[:-1])
        back_cur = list_dir[-1]
        if len(list_dir) == 1:
            back_prev = 'd'
            back_cur = list_dir[0]
        prev_dir += '%' + dir

        for d in list_dir:
            static_dir_root_path_folder += '/' + d
            static_dir_root_folder += '/' + d

        # for new folder
        static_dir_root_path_folder += '/' + str(dir)
        static_dir_root_path_folder = slash_remove_from_path(
            static_dir_root_path_folder)
        static_dir_root_folder += '/' + str(dir)
        static_dir_root_folder = slash_remove_from_path(static_dir_root_folder)
    else:
        # for new folder
        prev_dir = dir
        static_dir_root_path_folder = static_dir_root_path + '/' + str(dir)
        static_dir_root_path_folder = slash_remove_from_path(
            static_dir_root_path_folder)
        static_dir_root_folder = static_dir_root + '/' + str(dir)
        static_dir_root_folder = slash_remove_from_path(static_dir_root_folder)

    dirs, files, info_message = get_files_dirs(static_dir_root_folder,
                                               static_dir_root_path_folder)

    if info_message:
        info_message = u'For run "{0}" there are no results to show.'.format(
            run_base.name)

    data = {
        'run_id': run_id,
        'prev_dir': prev_dir,
        'title': title,
        'info_message': info_message,
        'dirs': dirs,
        'files': files,
        'back_prev': back_prev,
        'back_cur': back_cur
    }

    return data


# Resolution list
@login_required
@render_to('gsi/resolution_list.html')
def resolution(request):
    title = 'Resolutions'
    resolution = Resolution.objects.all()
    resolution_name = ''
    url_name = 'resolution'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name', 'value'):
            resolution = resolution.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                resolution = resolution.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Resolution, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)

        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(Resolution, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('resolution_select'):
            for satellite_id in request.POST.getlist('resolution_select'):
                cur_resolution = get_object_or_404(Resolution, pk=satellite_id)
                resolution_name += '"' + cur_resolution.name + '", '
                cur_resolution.delete()

            resolution_name = resolution_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('resolution'),
                (u'Resolutions "{0}" deleted.'.format(resolution_name))))
        elif request.POST.get('delete_button'):
            cur_resolution = get_object_or_404(
                Resolution, pk=request.POST.get('delete_button'))
            resolution_name += '"' + cur_resolution.name + '"'
            cur_resolution.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('resolution'),
                (u'Resolution "{0}" deleted.'.format(resolution_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('resolution'),
                (u"To delete, select Resolution or more Resolutions.")))

    # paginations
    model_name = paginations(request, resolution)

    data = {
        'title': title,
        'resolutions': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Resolution add
@login_required
@render_to('gsi/static_data_item_edit.html')
def resolution_add(request):
    title = 'Resolution Add'
    url_form = 'resolution_add'
    url_name = 'resolution'
    but_name = 'static_data'
    template_name = 'gsi/_resolution_form.html'
    reverse_url = {
        'save_button': 'resolution',
        'save_and_another': 'resolution_add',
        'save_and_continue': 'resolution_edit',
        'cancel_button': 'resolution'
    }
    func = resolution_update_create
    form = None
    available_resolution = Resolution.objects.all()

    if request.method == "POST":
        response = get_post(request, ResolutionForm, 'Resolution', reverse_url,
                            func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = ResolutionForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_resolution': available_resolution,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Resolution edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def resolution_edit(request, resolution_id):
    resolution = get_object_or_404(Resolution, pk=resolution_id)
    title = 'Resolution Edit "%s"' % (resolution.name)
    url_name = 'resolution'
    but_name = 'static_data'
    url_form = 'resolution_edit'
    template_name = 'gsi/_resolution_form.html'
    reverse_url = {
        'save_button': 'resolution',
        'save_and_another': 'resolution_add',
        'save_and_continue': 'resolution_edit',
        'cancel_button': 'resolution'
    }
    func = resolution_update_create
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            ResolutionForm,
            'Resolution',
            reverse_url,
            func,
            item_id=resolution_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = ResolutionForm(instance=resolution)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': resolution_id,
    }

    return data


# Tiles list
@login_required
@render_to('gsi/tiles_list.html')
def tiles(request):
    title = 'Tiles'
    tile = Tile.objects.all()
    tile_name = ''
    url_name = 'tiles'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name',):
            tile = tile.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                tile = tile.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Tile, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)

        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(Tile, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('tile_select'):
            for tile_id in request.POST.getlist('tile_select'):
                cur_tile = get_object_or_404(Tile, pk=tile_id)
                tile_name += '"' + cur_tile.name + '", '
                cur_tile.delete()

            tile_name = tile_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('tiles'),
                (u'Tiles "{0}" deleted.'.format(tile_name))))
        elif request.POST.get('delete_button'):
            cur_tile = get_object_or_404(
                Tile, pk=request.POST.get('delete_button'))
            tile_name += '"' + cur_tile.name + '"'
            cur_tile.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('tiles'),
                (u'Tile "{0}" deleted.'.format(tile_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('tiles'),
                (u"To delete, select Tile or more Tiles.")))

    # paginations
    model_name = paginations(request, tile)

    data = {
        'title': title,
        'tiles': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Tiles add
@login_required
@render_to('gsi/static_data_item_edit.html')
def tile_add(request):
    title = 'Tile Add'
    url_form = 'tile_add'
    url_name = 'tiles'
    but_name = 'static_data'
    template_name = 'gsi/_tile_form.html'
    reverse_url = {
        'save_button': 'tiles',
        'save_and_another': 'tile_add',
        'save_and_continue': 'tile_edit',
        'cancel_button': 'tiles'
    }
    func = tile_update_create
    form = None
    available_tiles = Tile.objects.all()

    if request.method == "POST":
        response = get_post(request, TileForm, 'Tile', reverse_url,
                            func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = TileForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_tiles': available_tiles,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Tiles edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def tile_edit(request, tile_id):
    tile = get_object_or_404(Tile, pk=tile_id)
    title = 'Tile Edit "%s"' % (tile.name)
    url_name = 'tiles'
    but_name = 'static_data'
    url_form = 'tile_edit'
    template_name = 'gsi/_tile_form.html'
    reverse_url = {
        'save_button': 'tiles',
        'save_and_another': 'tile_add',
        'save_and_continue': 'tile_edit',
        'cancel_button': 'tiles'
    }
    func = tile_update_create
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            TileForm,
            'Tile',
            reverse_url,
            func,
            item_id=tile_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = TileForm(instance=tile)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': tile_id,
    }

    return data


# Years list
@login_required
@render_to('gsi/years_list.html')
def years(request):
    title = 'Years'
    years = Year.objects.all().order_by('name')
    year_name = ''
    url_name = 'years'
    but_name = 'static_data'

    if request.method == "GET":
        order_by = request.GET.get('order_by', '')

        if order_by in ('name',):
            years = years.order_by(order_by)

            if request.GET.get('reverse', '') == '1':
                years = years.reverse()

    if request.method == "POST" and request.is_ajax():
        data_post = request.POST

        if 'run_id[]' in data_post:
            data = ''
            message = u'Are you sure you want to remove these objects:'
            run_id = data_post.getlist('run_id[]')

            for r in run_id:
                cur_run = get_object_or_404(Year, pk=int(r))
                data += '"' + cur_run.name + '", '

            data = data[:-2]
            data = '<b>' + data + '</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)

        if 'cur_run_id' in data_post:
            message = u'Are you sure you want to remove this objects:'
            run_id = data_post['cur_run_id']
            cur_run = get_object_or_404(Year, pk=int(run_id))
            data = '<b>"' + cur_run.name + '"</b>'
            data = '{0} {1}?'.format(message, data)

            return HttpResponse(data)
        else:
            data = ''
            return HttpResponse(data)

    if request.method == "POST":
        # if request.POST.get('delete_button'):
        if request.POST.get('year_select'):
            for year_id in request.POST.getlist('year_select'):
                cur_year = get_object_or_404(Year, pk=year_id)
                year_name += '"' + cur_year.name + '", '
                cur_year.delete()

            year_name = year_name[:-2]

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('years'),
                (u'Tiles "{0}" deleted.'.format(year_name))))
        elif request.POST.get('delete_button'):
            cur_year = get_object_or_404(
                Year, pk=request.POST.get('delete_button'))
            year_name += '"' + cur_year.name + '"'
            cur_year.delete()

            return HttpResponseRedirect(u'%s?status_message=%s' % (
                reverse('years'),
                (u'Year "{0}" deleted.'.format(year_name))))
        else:
            return HttpResponseRedirect(u'%s?warning_message=%s' % (
                reverse('years'),
                (u"To delete, select Year or more Years.")))

    # paginations
    model_name = paginations(request, years)

    data = {
        'title': title,
        'years': model_name,
        'model_name': model_name,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Year add
@login_required
@render_to('gsi/static_data_item_edit.html')
def year_add(request):
    title = 'Year Add'
    url_form = 'year_add'
    url_name = 'years'
    but_name = 'static_data'
    template_name = 'gsi/_year_form.html'
    reverse_url = {
        'save_button': 'years',
        'save_and_another': 'year_add',
        'save_and_continue': 'year_edit',
        'cancel_button': 'years'
    }
    func = year_update_create
    form = None
    available_years = Year.objects.all()

    if request.method == "POST":
        response = get_post(request, YearForm, 'Year', reverse_url,
                            func)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = YearForm()

    data = {
        'title': title,
        'url_form': url_form,
        'template_name': template_name,
        'form': form,
        'available_years': available_years,
        'url_name': url_name,
        'but_name': but_name,
    }

    return data


# Year edit
@login_required
@render_to('gsi/static_data_item_edit.html')
def year_edit(request, year_id):
    year = get_object_or_404(Year, pk=year_id)
    title = 'Year Edit "%s"' % (year.name)
    url_name = 'years'
    but_name = 'static_data'
    url_form = 'year_edit'
    template_name = 'gsi/_year_form.html'
    reverse_url = {
        'save_button': 'years',
        'save_and_another': 'year_add',
        'save_and_continue': 'year_edit',
        'cancel_button': 'years'
    }
    func = year_update_create
    form = None

    if request.method == "POST":
        response = get_post(
            request,
            YearForm,
            'Year',
            reverse_url,
            func,
            item_id=year_id)

        if isinstance(response, HttpResponseRedirect):
            return response
        else:
            form = response
    else:
        form = YearForm(instance=year)

    data = {
        'title': title,
        'url_form': url_form,
        'url_name': url_name,
        'but_name': but_name,
        'template_name': template_name,
        'form': form,
        'item_id': year_id,
    }

    return data


# view Customer section
@login_required
@render_to('gsi/customer_section.html')
def customer_section(request):
    customer = request.user
    title = 'Customer {0} section'.format(customer)
    url_name = 'customer_section'
    eLat = 0
    eLng = 0

    if request.method == "POST":
        data_request = request.POST

        if data_request.get('eLat', ''):
            eLat = data_request.get('eLat', '')

        if data_request.get('eLng', ''):
            eLng = data_request.get('eLng', '')


    data = {
        'title': title,
        'customer': customer,
        'url_name': url_name,
        'eLat': eLat,
        'eLng': eLng,
        'GOOGLE_MAP_ZOOM': GOOGLE_MAP_ZOOM
    }

    return data
