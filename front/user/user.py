from datetime import timedelta, datetime
import pandas as pd


def time_to_timedelta(t):
    return timedelta(hours=t.hour, minutes=t.minute, seconds=t.second)


class User:
    def __init__(self, user_id, conn):
        self.user_id = user_id
        self.conn = conn

    def _get_activity(self, table, wkt_id=None):
        query = f"""
            SELECT *
            FROM {table}
            WHERE user_id = :user_id
            """
        params = {'table': table, 'user_id': self.user_id}
        if wkt_id:
            query += 'activity_id = :wkt_id'
            params['activity_id'] = wkt_id
        return self.conn.query(query, params=params)

    def get_calendar(self):
        syn_run = self._get_activity('running.syn')
        syn_run = self._prep_calendar(syn_run, 'running')
        syn_cycling = self._get_activity('cycling.syn')
        syn_cycling = self._prep_calendar(syn_cycling, 'cycling')
        total = pd.concat([syn_run, syn_cycling], axis=0)
        return total

    def get_analysis(self, schema, wkt_id):
        table = f'{schema}.lap'
        df_laps = self._get_activity(table, wkt_id)
        df_laps = df_laps.drop(['activity_id', 'user_id', 'lap_id'], axis=1)
        df_laps['distance'] = df_laps['distance'] / 1000
        df_laps['distance'] = df_laps['distance'].round(2)

    def get_events(self):
        query = """
        SELECT date, name, sport, priority
        FROM param.events
        WHERE user_id = :user_id
        ORDER BY priority
        """
        params = {"user_id": self.user_id}
        return self.conn.query(query, params=params)

    def get_full_workouts(self):
        syn_run = self._get_activity('running.syn')
        syn_cycling = self._get_activity('cycling.syn')
        total = pd.concat([syn_run, syn_cycling], axis=0)

        total['week'] = total['date'].dt.isocalendar().week
        total['hour'] = total['duration'].apply(lambda x: x.hour)
        total['minute'] = total['duration'].apply(lambda x: x.minute)
        total['second'] = total['duration'].apply(lambda x: x.second)
        total['duration'] = total['hour'] * 3600 + total['minute'] * 60 + total['second']
        total['date'] = total['date'].dt.strftime('%Y-%m-%d')

        end_date = datetime.today()
        start_date = end_date - timedelta(days=92)
        date_range = pd.date_range(start=start_date, end=end_date)
        date_range = date_range.strftime('%Y-%m-%d')
        df = pd.DataFrame({'date': date_range})

        return df.merge(total, on='date', how='left')

    def get_threshold(self):
        query = """
            SELECT *
            FROM param.user_threshold
            WHERE user_id = :user_id
            ORDER BY date desc
            LIMIT 1
            """
        params = {'user_id': self.user_id}
        return self.conn.query(query, params=params)

    def _prep_calendar(self, data, sport):
        cols = ['activity_id', 'date', 'duration']
        data = data[cols]
        data['title'] = sport
        data['end'] = data.apply(lambda row: row['date'] + time_to_timedelta(row['duration']), axis=1)
        return data
