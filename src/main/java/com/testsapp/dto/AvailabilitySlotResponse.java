package com.testsapp.dto;
import java.time.LocalDateTime;
public record AvailabilitySlotResponse(
        LocalDateTime startTime,
        LocalDateTime endTime,
        boolean available,
        String reason
) {
}
