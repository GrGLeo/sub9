import os
import time
from sqlalchemy.exc import OperationalError
from fastapi import FastAPI, File, UploadFile, HTTPException, Form, status
from fitparse import FitFile
import pandas as pd
from sqlalchemy import create_engine
from back.data.etl.running_feeder import RunningFeeder
from back.data.etl.comment_feeder import CommentFeeder
from back.data.etl.event_feeder import EventFeeder
from back.data.etl.cycling_feeder import CyclingFeeder
from back.data.etl.threshold_feeder import ThresholdFeeder
from back.data.etl.futur_wkt_feeder import FuturWorkoutFeeder
from back.data.tables import Base
from back.data.utils import create_schema
from back.utils.exception import UserTaken, EmailTaken, UnknownUser, FailedAttempt, UserLocked
from back.utils.data_handler import get_data
from back.utils.logger import ConsoleLogger
from back.auth import auth_user, create_user
from back.fit.fit_writer import WorkoutWriter
from back.api_model import (
    UserModel,
    EventModel,
    LoginModel,
    CommentModel,
    ThresholdModel,
    FuturWktModel
)


DB_URL = os.getenv("DATABASE_URL", "leo:postgres@localhost:5432/sporting")
app = FastAPI()
logger = ConsoleLogger(__name__)


@app.on_event("startup")
async def startup_event():
    MAX_RETRIES = 10
    WAIT_TIME = 2
    DATABASE_URL = f"postgresql://{DB_URL}"
    engine = create_engine(DATABASE_URL)

    for attempt in range(MAX_RETRIES):
        try:
            Base.metadata.create_all(bind=engine)
            print("All tables are created or verified!")
            break
        except OperationalError:
            print(f"Database connection failed, retrying in {WAIT_TIME} seconds...")
            time.sleep(WAIT_TIME)
    else:
        print(f"Failed to connect to Database after {MAX_RETRIES} attemps.")


@app.post("/uploadfile/")
async def upload_file(
    file: UploadFile = File(...),
    user_id: int = Form(...)
):
    contents = await file.read()
    fitfile = FitFile(contents)
    records = get_data(fitfile, 'record')
    laps = get_data(fitfile, 'lap')
    activity = get_data(fitfile, 'session')[0]['sport']
    activity_id = int(records[0]["timestamp"].timestamp())

    wkt = {
        f"record_{activity}": pd.DataFrame(records),
        f"lap_{activity}": pd.DataFrame(laps)
    }

    if activity == "running":
        feeder = RunningFeeder(wkt, activity_id, int(user_id))
        feeder.compute()
    elif activity == "cycling":
        feeder = CyclingFeeder(wkt, activity_id, int(user_id))
        feeder.compute()
    if feeder.complete:
        return {
            "data": "Uploading successfull",
        }
    else:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='An error occured while uploading activity')


@app.post("/post_comment")
async def post_comment(comment: CommentModel):
    if len(comment.comment_text.strip()) == 0:
        logger.warning("Empty comment")
        raise HTTPException(status_code=400, detail="Comment can not be empty")

    try:
        comment_feeder = CommentFeeder(comment)
        comment_feeder.compute()
    except Exception as e:
        logger.error(e)
        pass


@app.post("/post_event")
async def post_event(event: EventModel):
    event_feeder = EventFeeder(event)
    event_feeder.compute()


@app.post("/threshold")
async def update_threshold(threshold: ThresholdModel):
    threshold_feeder = ThresholdFeeder(threshold)
    threshold_feeder.compute()


@app.post("/push_program_wkt")
async def save_program_wkt(futur_wkt: FuturWktModel):
    ftr_wkt_feeder = FuturWorkoutFeeder(futur_wkt)
    ftr_wkt_feeder.compute()
    wkt_writer = WorkoutWriter(futur_wkt)
    wkt_writer.write_workout()



@app.post("/login")
async def login(login_data: LoginModel):
    try:
        logger.info(f'User: {login_data.username} login attempt')
        token = auth_user(login_data.username, login_data.password)
    except UnknownUser as e:
        logger.warning(f'User: {login_data.username} {e}')
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except UserLocked as e:
        logger.warning(f'User: {login_data.username} {e}')
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=str(e))
    except FailedAttempt as e:
        logger.warning(f'User: {login_data.username} {e}')
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    logger.info(f'User: {login_data.username} login successfull')
    return {"token": token}


@app.post("/create_user")
async def create_new_user(new_user: UserModel):
    try:
        token = create_user(new_user.username, new_user.password, new_user.email)
    except (UserTaken, EmailTaken) as e:
        raise HTTPException(status_code=401, detail=f'{e}')
    return {"token": token}
