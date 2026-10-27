package com.ytell.zhiyuan.web.advice;

import com.ytell.zhiyuan.common.base.BaseResponse;
import com.ytell.zhiyuan.model.dto.planning.FixProposalApplyRes;
import com.ytell.zhiyuan.model.dto.planning.PendingPlanningCommandRes;
import com.ytell.zhiyuan.model.dto.planning.PlanningStateDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanningWorkspaceStateRes;
import com.ytell.zhiyuan.model.dto.planning.ReviewFixPreviewDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewStateDTO;
import com.ytell.zhiyuan.model.dto.planning.ReviewWorkflowRunRes;
import com.ytell.zhiyuan.service.biz.ReviewPolicy;
import org.springframework.core.MethodParameter;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;

/**
 * paused 的最后一层响应防线。
 *
 * <p>业务层已在新读入口做投影；这里兜住所有仍以 {@link PlanningStateDTO} 等旧形状
 * 返回的写接口，防止某个入口忘了投影就把历史 summary/checks 继续带出去。
 * 只改响应对象，不改落库状态。</p>
 */
@RestControllerAdvice
public class ReviewResponseProjectionAdvice implements ResponseBodyAdvice<Object> {

    @Override
    public boolean supports(MethodParameter returnType,
                            Class<? extends HttpMessageConverter<?>> converterType) {
        return true;
    }

    @Override
    public Object beforeBodyWrite(Object body, MethodParameter returnType,
                                  MediaType selectedContentType,
                                  Class<? extends HttpMessageConverter<?>> selectedConverterType,
                                  ServerHttpRequest request, ServerHttpResponse response) {
        if (!ReviewPolicy.paused()) {
            return body;
        }
        if (body instanceof BaseResponse) {
            @SuppressWarnings("rawtypes")
            BaseResponse base = (BaseResponse) body;
            base.setData(project(base.getData()));
            return base;
        }
        return body;
    }

    private Object project(Object data) {
        if (data instanceof ReviewStateDTO) {
            return ReviewPolicy.pausedProjection();
        }
        if (data instanceof PlanningStateDTO) {
            ReviewPolicy.projectForOutput((PlanningStateDTO) data);
            return data;
        }
        if (data instanceof PlanningWorkspaceStateRes) {
            ((PlanningWorkspaceStateRes) data).setReviewState(ReviewPolicy.pausedProjection());
            return data;
        }
        if (data instanceof ReviewFixPreviewDTO) {
            ReviewFixPreviewDTO preview = (ReviewFixPreviewDTO) data;
            preview.setReview(ReviewPolicy.pausedProjection());
            return preview;
        }
        if (data instanceof FixProposalApplyRes) {
            FixProposalApplyRes apply = (FixProposalApplyRes) data;
            ReviewPolicy.projectForOutput(apply.getState());
            return apply;
        }
        if (data instanceof PendingPlanningCommandRes) {
            PendingPlanningCommandRes command = (PendingPlanningCommandRes) data;
            command.setReviewState(ReviewPolicy.pausedProjection());
            ReviewPolicy.projectForOutput(command.getPlanningState());
            return command;
        }
        if (data instanceof ReviewWorkflowRunRes) {
            ReviewWorkflowRunRes workflow = (ReviewWorkflowRunRes) data;
            workflow.setReviewState(ReviewPolicy.pausedProjection());
            if (workflow.getWorkspaceState() != null) {
                workflow.getWorkspaceState().setReviewState(ReviewPolicy.pausedProjection());
            }
            return workflow;
        }
        return data;
    }
}
