from django.http import HttpResponse, HttpRequest, JsonResponse
from django.template import loader
from django.conf import settings

import controller.logic.job.helper_functions as job_helper_functions
import controller.logic.job.components as job_components
import controller.logic.job.data_access_operations as job_dao
import controller.logic.run.helper_functions as run_helper_functions
import controller.logic.run.components as run_components
import controller.logic.run.data_access_operations as run_dao
import controller.logic.pipelined_simulated_run.helper_functions as pipelined_simulated_run_helper_functions
from controller.logic.common_logic_operations import  parse_string_to_list_of_strings


def index(request: HttpRequest, job_name: str, job_type: str):
    """Return the job listing and options to manipulate them"""

    # get the available 3a_kn human jobs
    job_status = settings.JOB_STATUS[1]     # 'RUNNING'
    list_3a_kn_jobs = job_dao.find_all_jobs(job_name=job_name, job_type=job_type, job_status=job_status)

    # show on screen via the response
    context = {
        'section': 'worker',
        'list_3a_kn_jobs': list_3a_kn_jobs
    }
    template = loader.get_template('controller/job/job_management_index.html')
    response = HttpResponse(template.render(context, request))
    return response


def work(request: HttpRequest):
    """Assign a task to this worker and return annotation page"""

    # get this worker's id
    worker_id = request.user.id
    # get this job's identifiers
    requester_id, project_id, workflow_id, run_id, job_id = job_helper_functions.get_job_identifiers(request)

    obj_job: job_components.Job = job_dao.find_job(
        job_id=job_id,
        run_id=run_id,
        workflow_id=workflow_id,
        project_id=project_id,
        user_id=requester_id
    )
    request.session['current_job_requester'] = obj_job.user_id
    request.session['current_job_project'] = obj_job.project_id
    request.session['current_job_workflow'] = obj_job.workflow_id
    request.session['current_job_run'] = obj_job.run_id
    request.session['current_job'] = obj_job.id

    if obj_job.type == settings.OPERATOR_TYPES[1] and obj_job.name == settings.HUMAN_OPERATORS[0]:    # human, and 3a_kn
        # 1. prepare for assign and annotate
        # load worker instructions for this job,
        # and save it in session to fasten repeated access during successive assignments
        instructions_dict = job_dao.get_instructions(
            requester_id=requester_id,
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=run_id,
            job_id=job_id
        )
        for key, value in instructions_dict.items():
            if key == 'short_instructions':
                request.session['task_short_instructions'] = value
            elif key == 'long_instructions':
                request.session['task_long_instructions'] = value
        # load layout for this job, and save it in session to fasten repeated access during successive assignments
        layout_dict = job_dao.get_layout(
            requester_id=requester_id,
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=run_id,
            job_id=job_id
        )
        for key, value in layout_dict.items():
            if key == 'design_layout':
                request.session['task_design_layout'] = value
        # load config parameters for this job, , and save them in session to fasten repeated access during successive assignments
        configuration_dict = job_dao.get_configuration(
            requester_id=requester_id,
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=run_id,
            job_id=job_id
        )
        for key, value in configuration_dict.items():
            # pre-processing
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            if key == 'question':
                request.session['task_question'] = value
            elif key == 'answers':
                if value == settings.FREE_TEXT_ANSWER:  # free text
                    request.session['task_option_list'] = None
                else:
                    unparsed_answers: str = value
                    answers: list = parse_string_to_list_of_strings(unparsed_answers)
                    request.session['task_option_list'] = answers
            elif key == 'annotation_time_limit':
                # TODO: this int should come from type_data_value in j_configuration table. so the proper type should also have been added when the j_configuration table was created.
                request.session['task_annotation_time_limit'] = int(value)
            elif key == 'k':
                request.session['job_k'] = int(value)
            elif key == 'n':
                request.session['job_n'] = int(value)
        count_tasks: int = job_dao.get_count_tasks(obj_job=obj_job)
        request.session['count_tasks'] = count_tasks

        # 2. assign task to worker for this 3a_kn job
        task_id = job_helper_functions.assign_3a_kn(
            worker_id,
            obj_job,
            request.session['job_k'],
            request.session['job_n'],
            request.session['task_annotation_time_limit'],
            request.session['count_tasks']
        )
        request.session['assigned_task_id'] = task_id
        if task_id == 0:
            context = {
                'section': 'worker',
                'message': 'this worker did not get any task',
                'worker_code': settings.WORKER_CODES['DELAYED_RETRY']
            }
            # for api requests such as by simulated workers
            if 'python' in request.headers.get('User-Agent'):
                return JsonResponse(context)
            # usual case: for requests via GUI
            return HttpResponse(context)
        if task_id < 0:
            context = {
                'section': 'worker',
                'message': 'human operator is not collecting annotations for any task',
                'worker_code': settings.WORKER_CODES['QUIT']
            }
            # for api requests such as by simulated workers
            if 'python' in request.headers.get('User-Agent'):
                return JsonResponse(context)
            # usual case: for requests via GUI
            return HttpResponse(context)

        # 3. get_annotation_page for this task of 3a_kn job
        page_contents = job_helper_functions.get_annotation_page_3a_kn(
            obj_job=obj_job,
            task_id=task_id,
            task_question=request.session['task_question'],
            task_option_list=request.session['task_option_list'],
            task_annotation_time_limit=request.session['task_annotation_time_limit'],
            task_short_instructions=request.session['task_short_instructions'],
            task_long_instructions=request.session['task_long_instructions'],
            task_design_layout=request.session['task_design_layout']
        )
    else:
        raise ValueError("Operator not recognized, so cannot work on job")

    # show on screen via the response
    context = {
        'section': 'worker',
        'task_question': page_contents['task_question'],
        'task_representation': page_contents['task_representation'],
        'task_option_list': page_contents['task_option_list'],
        'task_short_instructions': page_contents['task_short_instructions'],
        'task_long_instructions': page_contents['task_long_instructions'],
        'header_value_dict': page_contents['header_value_dict'],
        'timer': page_contents['timer'],
        'worker_code': settings.WORKER_CODES['ANNOTATE']
    }
    # for api requests such as by simulated workers
    if 'python' in request.headers.get('User-Agent'):
        return JsonResponse(context)
    # usual case: for requests via GUI
    template = loader.get_template('controller/job/task_annotation_page.html')
    response = HttpResponse(template.render(context, request))
    return response


def process_annotation(request: HttpRequest):
    """Process the annotation provided by worker and subsequently assign a new task to this worker"""

    # retrieve ids from session variables
    requester_id = request.session['current_job_requester']
    project_id = request.session['current_job_project']
    workflow_id = request.session['current_job_workflow']
    run_id = request.session['current_job_run']
    job_id = request.session['current_job']
    obj_job: job_components.Job = job_dao.find_job(
        job_id=job_id,
        run_id=run_id,
        workflow_id=workflow_id,
        project_id=project_id,
        user_id=requester_id
    )
    job_k = request.session['job_k']
    job_n = request.session['job_n']
    count_tasks = request.session['count_tasks']
    task_annotation_time_limit = request.session['task_annotation_time_limit']
    worker_id = request.user.id
    task_id = request.session['assigned_task_id']
    selected_choice = request.POST['choice']
    # aggregate logic
    job_helper_functions.aggregate_3a_kn(
        obj_job=obj_job,
        job_k=job_k,
        job_n=job_n,
        worker_id=worker_id,
        task_id=task_id,
        answer=selected_choice
    )
    # assign task to worker for this 3a_kn job
    new_task_id = job_helper_functions.assign_3a_kn(
        worker_id,
        obj_job,
        job_k,
        job_n,
        task_annotation_time_limit,
        count_tasks
    )
    if new_task_id > 0: # assign returned a task
        request.session['assigned_task_id'] = new_task_id
        # get_annotation_page for this task of 3a_kn job
        page_contents = job_helper_functions.get_annotation_page_3a_kn(
            obj_job=obj_job,
            task_id=new_task_id,
            task_question=request.session['task_question'],
            task_option_list=request.session['task_option_list'],
            task_annotation_time_limit=request.session['task_annotation_time_limit'],
            task_short_instructions=request.session['task_short_instructions'],
            task_long_instructions=request.session['task_long_instructions'],
            task_design_layout=request.session['task_design_layout']
        )
        # show on screen via the response
        context = {
            'section': 'worker',
            'task_question': page_contents['task_question'],
            'task_representation': page_contents['task_representation'],
            'task_option_list': page_contents['task_option_list'],
            'task_short_instructions': page_contents['task_short_instructions'],
            'task_long_instructions': page_contents['task_long_instructions'],
            'header_value_dict': page_contents['header_value_dict'],
            'timer': page_contents['timer'],
            'debug_message': 'worker_id: ' + str(worker_id),
            'worker_code': settings.WORKER_CODES['ANNOTATE']
        }
        # for api requests such as by simulated workers
        if 'python' in request.headers.get('User-Agent'):
            return JsonResponse(context)
        # usual case: for requests via GUI
        template = loader.get_template('controller/job/task_annotation_page.html')
        response = HttpResponse(template.render(context, request))
        return response
    elif new_task_id == 0:
        # this worker did not get any task from this job
        context = {
            'section': 'worker',
            'message': 'This job is still running but no available task at the moment.',
            'debug_message': 'worker_id: ' + str(worker_id),
            'worker_code': settings.WORKER_CODES['DELAYED_RETRY']
        }
        # for api requests such as by simulated workers
        if 'python' in request.headers.get('User-Agent'):
            return JsonResponse(context)
        # usual case: for requests via GUI
        template = loader.get_template('controller/job/no_available_task.html')
        response = HttpResponse(template.render(context, request))
        return response
    else:  # new_task_id < 0:
        """
        the commented case below is impossible to happen theoretically. 
        But, keep the comments in case you run into the issue just as to solve it later.
        if two workers enter here at the same time, you don't want to complete job and progress dag two times.
        So, maybe within the below function, check if the job is not complete, lock it, 
            do bookkeeping, mark it complete (and unlock).
        if the job was completed already when you are trying to lock, return void there and then, 
            notify the worker of no more tasks accepted.
        """
        obj_run: run_components.Run = run_dao.find_run(run_id=run_id, workflow_id=workflow_id, project_id=project_id, user_id=requester_id)
        if obj_run.type == settings.RUN_TYPES[2]:   # pipelined run
            pipelined_simulated_run_helper_functions.complete_processing_job_and_progress_dag(this_job=obj_job)
        else:
            # human operator just finished, do bookkeeping and mark complete; and progress dag
            run_helper_functions.complete_processing_job_and_progress_dag(this_job=obj_job)
        # return and notify the user (worker) that job has finished, and take the worker back to job listing page
        # human operator is not collecting annotations for any task
        context = {
            'section': 'worker',
            'message': 'This job has completed, and not collecting any more annotations.',
            'debug_message': 'worker_id: ' + str(worker_id),
            'worker_code': settings.WORKER_CODES['QUIT']
        }
        # for api requests such as by simulated workers
        if 'python' in request.headers.get('User-Agent'):
            return JsonResponse(context)
        # usual case: for requests via GUI
        template = loader.get_template('controller/job/no_available_task.html')
        response = HttpResponse(template.render(context, request))
        return response


def quit(request: HttpRequest):
    """Worker wants to quit annotating"""

    # retrieve ids from session variables
    requester_id = request.session['current_job_requester']
    project_id = request.session['current_job_project']
    workflow_id = request.session['current_job_workflow']
    run_id = request.session['current_job_run']
    job_id = request.session['current_job']
    obj_job: job_components.Job = job_dao.find_job(
        job_id=job_id,
        run_id=run_id,
        workflow_id=workflow_id,
        project_id=project_id,
        user_id=requester_id
    )
    worker_id = request.user.id
    task_id = request.session['assigned_task_id']
    # reclaim task: update tasks and task assignments table
    job_dao.skip_3a_kn(obj_job=obj_job, task_id=task_id, worker_id=worker_id)
    # return 'successfully quit' screen
    context = {
        'section': 'worker',
        'message': 'You pressed the quit button and have quit the job successfully'
    }
    # for api requests such as by simulated workers
    if 'python' in request.headers.get('User-Agent'):
        return JsonResponse(context)
    # usual case: for requests via GUI
    template = loader.get_template('controller/job/job_quitted.html')
    response = HttpResponse(template.render(context, request))
    return response


def skip(request: HttpRequest):
    """Worker wants to skip annotating"""

    # retrieve ids from session variables
    requester_id = request.session['current_job_requester']
    project_id = request.session['current_job_project']
    workflow_id = request.session['current_job_workflow']
    run_id = request.session['current_job_run']
    job_id = request.session['current_job']
    obj_job: job_components.Job = job_dao.find_job(
        job_id=job_id,
        run_id=run_id,
        workflow_id=workflow_id,
        project_id=project_id,
        user_id=requester_id
    )
    job_k = request.session['job_k']
    job_n = request.session['job_n']
    count_tasks = request.session['count_tasks']
    task_annotation_time_limit = request.session['task_annotation_time_limit']
    worker_id = request.user.id
    task_id = request.session['assigned_task_id']
    # reclaim task: update tasks and task assignments table
    job_dao.skip_3a_kn(obj_job=obj_job, task_id=task_id, worker_id=worker_id)

    # assign a new task to worker for this 3a_kn job
    new_task_id = job_helper_functions.assign_3a_kn(
        worker_id,
        obj_job,
        job_k,
        job_n,
        task_annotation_time_limit,
        count_tasks
    )
    if new_task_id > 0:  # assign returned a task
        request.session['assigned_task_id'] = new_task_id
        # get_annotation_page for this task of 3a_kn job
        page_contents = job_helper_functions.get_annotation_page_3a_kn(
            obj_job=obj_job,
            task_id=new_task_id,
            task_question=request.session['task_question'],
            task_option_list=request.session['task_option_list'],
            task_annotation_time_limit=request.session['task_annotation_time_limit'],
            task_short_instructions=request.session['task_short_instructions'],
            task_long_instructions=request.session['task_long_instructions'],
            task_design_layout=request.session['task_design_layout']
        )
        # show on screen via the response
        context = {
            'section': 'worker',
            'task_question': page_contents['task_question'],
            'task_representation': page_contents['task_representation'],
            'task_option_list': page_contents['task_option_list'],
            'task_short_instructions': page_contents['task_short_instructions'],
            'task_long_instructions': page_contents['task_long_instructions'],
            'header_value_dict': page_contents['header_value_dict'],
            'timer': page_contents['timer'],
            'debug_message': 'worker_id: ' + str(worker_id),
            'worker_code': settings.WORKER_CODES['ANNOTATE']
        }
        # for api requests such as by simulated workers
        if 'python' in request.headers.get('User-Agent'):
            return JsonResponse(context)
        # usual case: for requests via GUI
        template = loader.get_template('controller/job/task_annotation_page.html')
        response = HttpResponse(template.render(context, request))
        return response
    elif new_task_id == 0:
        # this worker did not get any task from this job
        context = {
            'section': 'worker',
            'message': 'This job is still running but no available task at the moment.',
            'debug_message': 'worker_id: ' + str(worker_id),
            'worker_code': settings.WORKER_CODES['DELAYED_RETRY']
        }
        # for api requests such as by simulated workers
        if 'python' in request.headers.get('User-Agent'):
            return JsonResponse(context)
        # usual case: for requests via GUI
        template = loader.get_template('controller/job/no_available_task.html')
        response = HttpResponse(template.render(context, request))
        return response
    else:  # new_task_id < 0:
        """
        We just skipped a task. It is not possible that the job has completed. 
        Even if some other user picked up the task we just skipped, and completed it, 
        that user's call to process_annotation will complete the job and progress the dag.
        So we don't need to do anything here.
        """
        raise ValueError("You just skipped a task, but the job is completed. This should not happen.")
