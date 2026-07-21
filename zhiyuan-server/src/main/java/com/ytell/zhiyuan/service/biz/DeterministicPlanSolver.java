package com.ytell.zhiyuan.service.biz;

import com.ytell.zhiyuan.model.dto.planning.PlanSolverInputDTO;
import com.ytell.zhiyuan.model.dto.planning.PlanSolverResultDTO;

interface DeterministicPlanSolver {
    PlanSolverResultDTO solve(PlanSolverInputDTO input);
}
