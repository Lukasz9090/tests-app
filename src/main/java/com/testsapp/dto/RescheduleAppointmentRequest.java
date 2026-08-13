package com.testsapp.dto;
import java.time.LocalDateTime;
public record RescheduleAppointmentRequest(LocalDateTime newStartTime) {
}
