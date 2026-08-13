package com.testsapp.dto;
import com.testsapp.domain.AppointmentStatus;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;
public record DashboardResponse(
        long totalServices,
        long totalAppointments,
        Map<AppointmentStatus, Long> countsByStatus,
        BigDecimal projectedRevenue,
        BigDecimal realizedRevenue,
        LocalDateTime nextAppointmentStart
) {
}
