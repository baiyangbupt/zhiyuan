alter table assistant_user_base
    add limit_settings varchar(1024) null comment '操作限制配置' after user_score;

alter table assistant_user_base
    add channel varchar(12) default 'ytell' null comment '渠道' after limit_settings;

alter table assistant_user_credential
    add channel varchar(12) default 'ytell' not null after login_type;