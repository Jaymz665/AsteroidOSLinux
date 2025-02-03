import pyowm

def get_forecast_data(api_key, city_name):
    owm = pyowm.OWM(api_key)

    mgr = owm.weather_manager()

    forecast = mgr.forecast_at_place(city_name, '3h')

    max_temp = []
    min_temp = []
    weather_ids = []

    total_weathers = len(forecast.forecast.weathers)

    for i in range(min(total_weathers // 8, 5)):
        day_index_start = i * 8  
        day_index_end = (i + 1) * 8  
        
        start_index = max(day_index_start, 0)
        end_index = min(day_index_end, total_weathers)
        
        day_temps = [forecast.forecast.weathers[j].temperature('kelvin')['temp'] for j in range(start_index, end_index)]
        min_temp.append(min(day_temps))
        max_temp.append(max(day_temps))

        weather_ids.append(forecast.forecast.weathers[start_index].weather_code)

    length = min(len(weather_ids), len(min_temp), len(max_temp))

    return weather_ids[:length], min_temp[:length], max_temp[:length]
