package com.testsapp.service;

import com.testsapp.domain.Appointment;
import com.testsapp.domain.AppointmentStatus;
import com.testsapp.domain.NotificationChannel;
import com.testsapp.domain.NotificationMessage;
import com.testsapp.domain.NotificationType;
import com.testsapp.dto.NotificationResponse;
import com.testsapp.exception.ApiException;
import com.testsapp.repository.AppointmentRepository;
import com.testsapp.repository.NotificationRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;

@Service
public class NotificationService {
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    private final NotificationRepository notificationRepository;
    private final AppointmentRepository appointmentRepository;

    public NotificationService(NotificationRepository notificationRepository, AppointmentRepository appointmentRepository) {
        this.notificationRepository = notificationRepository;
        this.appointmentRepository = appointmentRepository;
    }

    public List<NotificationResponse> listNotifications(String customerEmail, Long appointmentId) {
        return notificationRepository.findAll().stream()
                .filter(item -> customerEmail == null || customerEmail.isBlank() || item.getCustomerEmail().equalsIgnoreCase(customerEmail.trim()))
                .filter(item -> appointmentId == null || item.getAppointmentId() == appointmentId)
                .map(this::toResponse)
                .toList();
    }

    public NotificationResponse sendAppointmentCreatedNotification(Appointment appointment) {
        NotificationMessage message = buildMessage(
                appointment,
                NotificationType.APPOINTMENT_CREATED,
                "Potwierdzenie wizyty #" + appointment.getId(),
                "Twoja wizyta " + appointment.getServiceName() + " zostala zaplanowana na " + formatDateTime(appointment.getStartTime()) + "."
        );
        return toResponse(notificationRepository.save(message));
    }

    public NotificationResponse sendAppointmentCancelledNotification(Appointment appointment) {
        NotificationMessage message = buildMessage(
                appointment,
                NotificationType.APPOINTMENT_CANCELLED,
                "Anulowanie wizyty #" + appointment.getId(),
                "Wizyta " + appointment.getServiceName() + " zaplanowana na " + formatDateTime(appointment.getStartTime()) + " zostala anulowana."
        );
        return toResponse(notificationRepository.save(message));
    }

    public NotificationResponse sendAppointmentRescheduledNotification(Appointment appointment, LocalDateTime previousStartTime) {
        NotificationMessage message = buildMessage(
                appointment,
                NotificationType.APPOINTMENT_RESCHEDULED,
                "Zmiana terminu wizyty #" + appointment.getId(),
                "Wizyta " + appointment.getServiceName() + " zostala przelozona z " + formatDateTime(previousStartTime) + " na " + formatDateTime(appointment.getStartTime()) + "."
        );
        return toResponse(notificationRepository.save(message));
    }

    public NotificationResponse sendReminderForAppointment(long appointmentId) {
        Appointment appointment = getScheduledAppointmentOrThrow(appointmentId);
        NotificationMessage message = buildMessage(
                appointment,
                NotificationType.APPOINTMENT_REMINDER,
                "Przypomnienie o wizycie #" + appointment.getId(),
                "Przypomnienie: wizyta " + appointment.getServiceName() + " odbedzie sie " + formatDateTime(appointment.getStartTime()) + "."
        );
        return toResponse(notificationRepository.save(message));
    }

    public int dispatchUpcomingReminders(Duration horizon) {
        Duration effectiveHorizon = (horizon == null || horizon.isNegative() || horizon.isZero())
                ? Duration.ofHours(24)
                : horizon;
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime deadline = now.plus(effectiveHorizon);
        List<Appointment> upcoming = appointmentRepository.findUpcoming(now);

        int created = 0;
        for (Appointment appointment : upcoming) {
            if (appointment.getStartTime().isAfter(deadline)) {
                continue;
            }
            if (notificationRepository.hasReminderForAppointmentOnDate(appointment.getId(), LocalDate.now())) {
                continue;
            }
            sendReminderForAppointment(appointment.getId());
            created++;
        }
        return created;
    }

    private Appointment getScheduledAppointmentOrThrow(long id) {
        Appointment appointment = appointmentRepository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "Nie znaleziono wizyty o id=" + id));
        if (appointment.getStatus() != AppointmentStatus.SCHEDULED) {
            throw new ApiException(HttpStatus.CONFLICT, "Powiadomienie mozna wyslac tylko dla zaplanowanej wizyty.");
        }
        return appointment;
    }

    private NotificationMessage buildMessage(Appointment appointment, NotificationType type, String subject, String content) {
        return new NotificationMessage(
                appointment.getId(),
                appointment.getCustomerEmail(),
                appointment.getCustomerName(),
                type,
                NotificationChannel.EMAIL,
                subject,
                content
        );
    }

    private NotificationResponse toResponse(NotificationMessage message) {
        return new NotificationResponse(
                message.getId(),
                message.getAppointmentId(),
                message.getCustomerEmail(),
                message.getCustomerName(),
                message.getType(),
                message.getChannel(),
                message.getSubject(),
                message.getContent(),
                message.getCreatedAt()
        );
    }

    private String formatDateTime(LocalDateTime dateTime) {
        return DATE_TIME_FORMATTER.format(dateTime);
    }
}

