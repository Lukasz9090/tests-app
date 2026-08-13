package com.testsapp.dto;
import com.testsapp.domain.AppointmentStatus;
import java.math.BigDecimal;
import java.time.LocalDateTime;
public record AppointmentResponse(
        long id,
        long serviceOfferId,
        String serviceName,
        String customerName,
        String customerEmail,
        LocalDateTime startTime,
        LocalDateTime endTime,
        AppointmentStatus status,
        BigDecimal price,
        String notes,
        LocalDateTime createdAt,
        LocalDateTime updatedAt
) {
}
