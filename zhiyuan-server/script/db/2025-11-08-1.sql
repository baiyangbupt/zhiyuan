update assistant_user_base
set expired_date = date_add(current_timestamp, interval 7 day)
where expired_date is null
   or expired_date <= current_timestamp;

