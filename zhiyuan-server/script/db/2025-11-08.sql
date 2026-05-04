alter table assistant_user_base
    add expired_date datetime default CURRENT_TIMESTAMP not null comment '用户账号过期时间' after limit_settings;

alter table assistant_user_base
    add user_level varchar(16) default 'ORIGIN' not null comment '用户等级' after expired_date;

