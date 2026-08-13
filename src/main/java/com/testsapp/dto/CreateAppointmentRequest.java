package com.testsapp.dto;
import java.time.LocalDateTime;
public record CreateAppointmentRequest(
        long serviceOfferId,
        String customerName,
        String customerEmail,
        LocalDateTime startTime,
        String notes
) {
}
